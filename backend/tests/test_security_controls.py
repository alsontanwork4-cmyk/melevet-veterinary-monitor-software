from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, settings
from app.database import Base, SQLiteBusyError, get_db
from app.models import Patient, User, UserSession
from app.routers import auth as auth_router
from app.routers import decode as decode_router
from app.routers import encounters as encounters_router
from app.routers import patients as patients_router
from app.routers import staged_uploads as staged_uploads_router
from app.routers import uploads as uploads_router
from app.services.auth_service import ensure_bootstrap_user, enforce_csrf, hash_password, require_active_user
from app.services.write_coordinator import ExclusiveWriteBusyError


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def _override_get_db(session_factory) -> Generator[Session, None, None]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def _build_secured_client(session_factory) -> TestClient:
    app = FastAPI()

    def override():
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = override
    app.exception_handler(ExclusiveWriteBusyError)(_exclusive_write_busy_handler)
    app.exception_handler(SQLiteBusyError)(_sqlite_busy_handler)
    protected = [Depends(require_active_user), Depends(enforce_csrf)]
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(patients_router.router, prefix="/api", dependencies=protected)
    return TestClient(app)


def _build_upload_client(session_factory, *, staged: bool = False, protected: bool = False) -> TestClient:
    app = FastAPI()

    def override():
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = override
    app.exception_handler(ExclusiveWriteBusyError)(_exclusive_write_busy_handler)
    app.exception_handler(SQLiteBusyError)(_sqlite_busy_handler)
    router = staged_uploads_router.router if staged else uploads_router.router
    if protected:
        auth_dependencies = [Depends(require_active_user), Depends(enforce_csrf)]
        app.include_router(auth_router.router, prefix="/api")
        app.include_router(router, prefix="/api", dependencies=auth_dependencies)
    else:
        app.include_router(router, prefix="/api")
    return TestClient(app)


def _build_protected_router_client(session_factory, router) -> TestClient:
    app = FastAPI()

    def override():
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = override
    app.exception_handler(ExclusiveWriteBusyError)(_exclusive_write_busy_handler)
    app.exception_handler(SQLiteBusyError)(_sqlite_busy_handler)
    protected = [Depends(require_active_user), Depends(enforce_csrf)]
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(router, prefix="/api", dependencies=protected)
    return TestClient(app)


def _seed_user(session_factory, *, username: str = "admin", password: str = "Passw0rd!") -> None:
    with session_factory() as db:
        db.add(User(username=username, password_hash=hash_password(password), is_active=True))
        db.commit()


def _login(client: TestClient, *, username: str = "admin", password: str = "Passw0rd!") -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


async def _exclusive_write_busy_handler(_request: Request, exc: ExclusiveWriteBusyError):
    return JSONResponse(status_code=409, content={"detail": exc.detail})


async def _sqlite_busy_handler(_request: Request, exc: SQLiteBusyError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def test_protected_patient_routes_require_login_and_csrf() -> None:
    session_factory = _session_factory()
    with session_factory() as db:
        db.add(User(username="admin", password_hash=hash_password("Passw0rd!"), is_active=True))
        db.add(Patient(patient_id_code="P-001", name="Patient One", species="Dog"))
        db.commit()

    client = _build_secured_client(session_factory)

    unauthenticated = client.get("/api/patients")
    assert unauthenticated.status_code == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "Passw0rd!"})
    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    assert login.cookies.get(settings.csrf_cookie_name) == csrf_token

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    session = client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["username"] == "admin"
    session_csrf_token = session.json()["csrf_token"]
    assert isinstance(session_csrf_token, str)
    assert session_csrf_token == csrf_token

    patient_list = client.get("/api/patients")
    assert patient_list.status_code == 200
    assert patient_list.json()["total"] == 1
    assert len(patient_list.json()["items"]) == 1

    logout_without_csrf = client.post("/api/auth/logout")
    assert logout_without_csrf.status_code == 403

    logout_with_csrf = client.post("/api/auth/logout", headers={settings.csrf_header_name: session_csrf_token})
    assert logout_with_csrf.status_code == 200
    assert logout_with_csrf.json() == {"logged_out": True}


def test_auth_session_reuses_existing_csrf_cookie_without_mutating_session_row() -> None:
    session_factory = _session_factory()
    _seed_user(session_factory)
    client = _build_secured_client(session_factory)

    login_response = client.post("/api/auth/login", json={"username": "admin", "password": "Passw0rd!"})
    assert login_response.status_code == 200
    csrf_token = login_response.json()["csrf_token"]

    with session_factory() as db:
        before = db.scalar(select(UserSession).where(UserSession.user_id == 1))
        assert before is not None
        before_hash = before.csrf_token_hash
        before_last_seen = before.last_seen_at

    session_response = client.get("/api/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["csrf_token"] == csrf_token

    with session_factory() as db:
        after = db.scalar(select(UserSession).where(UserSession.user_id == 1))
        assert after is not None
        assert after.csrf_token_hash == before_hash
        assert after.last_seen_at == before_last_seen


def test_auth_session_returns_401_without_session() -> None:
    session_factory = _session_factory()
    _seed_user(session_factory)
    client = _build_secured_client(session_factory)

    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.parametrize(
    ("router", "path"),
    [
        (patients_router.router, "/api/patients"),
        (uploads_router.router, "/api/uploads/123"),
        (staged_uploads_router.router, "/api/staged-uploads/demo-stage"),
        (encounters_router.router, "/api/encounters/123"),
        (decode_router.router, "/api/decode/jobs/demo-job"),
    ],
)
def test_protected_routes_return_401_without_session(router, path: str) -> None:
    session_factory = _session_factory()
    client = _build_protected_router_client(session_factory, router)

    response = client.get(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.parametrize("filename", ["..\\..\\evil.data", "../evil.data"])
def test_staged_upload_rejects_path_traversal_filename(tmp_path, filename: str) -> None:
    session_factory = _session_factory()
    original_stage_dir = settings.stage_storage_dir
    settings.stage_storage_dir = str(tmp_path / "staged")
    try:
        _seed_user(session_factory)
        client = _build_upload_client(session_factory, staged=True, protected=True)
        csrf_token = _login(client)
        response = client.post(
            "/api/staged-uploads",
            data={
                "patient_id_code": "P-002",
                "patient_name": "Stage Patient",
                "patient_species": "Dog",
                "timezone": "UTC",
            },
            headers={settings.csrf_header_name: csrf_token},
            files={
                "trend_data": (filename, b"1234", "application/octet-stream"),
                "trend_index": ("TrendChartRecord.Index", b"5678", "application/octet-stream"),
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid upload filename"
        assert not any(tmp_path.rglob("evil.data"))
    finally:
        settings.stage_storage_dir = original_stage_dir


def test_direct_upload_rejects_oversized_file(tmp_path) -> None:
    session_factory = _session_factory()
    original_spool_dir = settings.upload_spool_dir
    original_max_file_bytes = settings.max_upload_file_bytes
    original_max_request_bytes = settings.max_upload_request_bytes
    settings.upload_spool_dir = str(tmp_path / "spool")
    settings.max_upload_file_bytes = 4
    settings.max_upload_request_bytes = 8
    try:
        _seed_user(session_factory)
        client = _build_upload_client(session_factory, staged=False, protected=True)
        csrf_token = _login(client)
        response = client.post(
            "/api/uploads",
            data={
                "patient_id_code": "P-003",
                "patient_name": "Upload Patient",
                "patient_species": "Dog",
                "timezone": "UTC",
            },
            headers={settings.csrf_header_name: csrf_token},
            files={
                "trend_data": ("TrendChartRecord.data", b"12345", "application/octet-stream"),
            },
        )

        assert response.status_code == 413
        assert response.json()["detail"] == "Upload exceeds configured size limits"
    finally:
        settings.upload_spool_dir = original_spool_dir
        settings.max_upload_file_bytes = original_max_file_bytes
        settings.max_upload_request_bytes = original_max_request_bytes


def test_production_settings_require_secure_explicit_cors_and_disable_docs() -> None:
    with pytest.raises(ValueError, match="explicit CORS_ORIGINS"):
        Settings(app_env="production", cors_origins="").validate_runtime_settings()

    with pytest.raises(ValueError, match="HTTPS origins"):
        Settings(app_env="production", cors_origins="http://localhost:5173").validate_runtime_settings()

    production_settings = Settings(app_env="production", cors_origins="https://app.example.com")
    production_settings.validate_runtime_settings()
    assert production_settings.docs_enabled is False


def test_local_app_settings_use_appdata_and_allow_empty_cors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    local_settings = Settings(
        app_mode="local",
        app_env="production",
        cors_origins="",
        database_url="sqlite:///./melevet.db",
    )

    local_settings.validate_runtime_settings()
    assert local_settings.docs_enabled is False
    assert local_settings.resolved_database_url == f"sqlite:///{(tmp_path / 'Melevet' / 'melevet.db').as_posix()}"
    assert local_settings.resolved_stage_storage_dir == (tmp_path / "Melevet" / "staged_uploads")
    assert local_settings.resolved_upload_spool_dir == (tmp_path / "Melevet" / "upload_spool")


def test_bootstrap_user_is_created_when_credentials_are_configured() -> None:
    session_factory = _session_factory()
    original_username = settings.auth_bootstrap_username
    original_password = settings.auth_bootstrap_password
    settings.auth_bootstrap_username = "bootstrap-admin"
    settings.auth_bootstrap_password = "Passw0rd!"
    try:
        with session_factory() as db:
            user = ensure_bootstrap_user(db)
            assert user is not None
            assert user.username == "bootstrap-admin"

        with session_factory() as db:
            users = db.query(User).order_by(User.id.asc()).all()
            assert len(users) == 1
            assert users[0].username == "bootstrap-admin"
    finally:
        settings.auth_bootstrap_username = original_username
        settings.auth_bootstrap_password = original_password


def test_bootstrap_user_raises_clear_error_when_credentials_missing() -> None:
    session_factory = _session_factory()
    original_username = settings.auth_bootstrap_username
    original_password = settings.auth_bootstrap_password
    settings.auth_bootstrap_username = None
    settings.auth_bootstrap_password = None
    try:
        with session_factory() as db:
            with pytest.raises(RuntimeError, match=r"AUTH_BOOTSTRAP_USERNAME.*backend/.env"):
                ensure_bootstrap_user(db)
    finally:
        settings.auth_bootstrap_username = original_username
        settings.auth_bootstrap_password = original_password


def test_default_database_url_points_to_backend_sqlite_file() -> None:
    assert settings.database_url == "sqlite:///./melevet.db"
    assert settings.resolved_database_url.endswith("/melevet.db")
