from __future__ import annotations

import sqlite3
from collections.abc import Generator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import Base, SQLiteBusyError, get_db
from app.models import Patient, User
from app.routers import auth as auth_router
from app.routers import patients as patients_router
from app.services.auth_service import enforce_csrf, hash_password, require_active_user
from app.services.write_coordinator import ExclusiveWriteBusyError, exclusive_write


def _session_factory(db_path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 0.05},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=50;")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def _override_get_db(session_factory) -> Generator[Session, None, None]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


async def _exclusive_write_busy_handler(_request: Request, exc: ExclusiveWriteBusyError):
    return JSONResponse(status_code=409, content={"detail": exc.detail})


async def _sqlite_busy_handler(_request: Request, exc: SQLiteBusyError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _build_client(session_factory) -> TestClient:
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


def _seed_user_and_patient(session_factory) -> int:
    with session_factory() as db:
        db.add(User(username="admin", password_hash=hash_password("Passw0rd!"), is_active=True))
        patient = Patient(
            patient_id_code="LOCK-1",
            name="Locked Patient",
            species="Dog",
            owner_name="Client A",
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
        return patient.id


def _login(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "Passw0rd!"})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_auth_session_is_read_only_while_sqlite_writer_lock_is_held(tmp_path) -> None:
    original_attempts = settings.sqlite_lock_retry_attempts
    original_delay = settings.sqlite_lock_retry_delay_ms
    try:
        settings.sqlite_lock_retry_attempts = 2
        settings.sqlite_lock_retry_delay_ms = 10

        db_path = tmp_path / "lock-test.db"
        session_factory = _session_factory(db_path)
        patient_id = _seed_user_and_patient(session_factory)
        client = _build_client(session_factory)
        csrf_token = _login(client)

        raw_connection = sqlite3.connect(str(db_path), timeout=0.05, isolation_level=None)
        try:
            raw_connection.execute("PRAGMA journal_mode=WAL;")
            raw_connection.execute("BEGIN IMMEDIATE")
            raw_connection.execute("UPDATE users SET username = username WHERE id = 1")

            delete_response = client.delete(
                f"/api/patients/{patient_id}",
                headers={settings.csrf_header_name: csrf_token},
            )
            assert delete_response.status_code == 503
            assert "temporarily busy" in delete_response.json()["detail"].lower()

            session_response = client.get("/api/auth/session")
            assert session_response.status_code == 200
            assert session_response.json()["csrf_token"] == csrf_token
        finally:
            raw_connection.execute("ROLLBACK")
            raw_connection.close()
    finally:
        settings.sqlite_lock_retry_attempts = original_attempts
        settings.sqlite_lock_retry_delay_ms = original_delay


def test_patient_delete_returns_conflict_while_upload_write_lock_is_active(tmp_path) -> None:
    db_path = tmp_path / "coordination-test.db"
    session_factory = _session_factory(db_path)
    patient_id = _seed_user_and_patient(session_factory)
    client = _build_client(session_factory)
    csrf_token = _login(client)

    with exclusive_write(
        "upload persistence",
        wait=True,
        busy_detail="Upload persistence is already in progress.",
    ):
        response = client.delete(
            f"/api/patients/{patient_id}",
            headers={settings.csrf_header_name: csrf_token},
        )

    assert response.status_code == 409
    assert "temporarily unavailable" in response.json()["detail"].lower()
