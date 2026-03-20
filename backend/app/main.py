from contextlib import asynccontextmanager
import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import APP_VERSION, settings
from .database import (
    Base,
    SessionLocal,
    SQLiteBusyError,
    engine,
    ensure_sqlite_alarm_hard_removal,
    ensure_sqlite_core_storage_compaction,
    ensure_sqlite_upload_dedup_schema,
    ensure_sqlite_upload_progress_columns,
)
from .routers import archives, audit, auth, database_stats, decode, encounters, export, patients, sessions, settings as settings_router, staged_uploads, telemetry, updates, uploads
from .services.auth_service import enforce_csrf, ensure_bootstrap_user, purge_expired_sessions, require_active_user
from .services.archive_service import run_archival
from .services.logging_service import set_request_id
from .services.local_runtime import (
    configure_runtime_logging,
    ensure_runtime_directories,
    hold_local_runtime_lock,
)
from .services.staged_upload_service import purge_expired_staged_uploads
from .services.update_check_service import refresh_update_status
from .services.upload_service import (
    fail_stale_processing_uploads,
    purge_duplicate_orphan_uploads,
    purge_stale_orphan_uploads,
)
from .services.write_coordinator import ExclusiveWriteBusyError, exclusive_write


settings.validate_runtime_settings()
configure_runtime_logging()
logger = logging.getLogger(__name__)


def _frontend_index_path() -> Path | None:
    index_path = settings.frontend_dist_path / "index.html"
    return index_path if index_path.exists() else None


def _frontend_file_path(path: str) -> Path | None:
    candidate = (settings.frontend_dist_path / path).resolve()
    try:
        candidate.relative_to(settings.frontend_dist_path.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() and candidate.is_file() else None


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_started_at = perf_counter()
    ensure_runtime_directories()
    runtime_lock = hold_local_runtime_lock()
    logger.info("Starting %s version %s", settings.app_name, APP_VERSION)

    with exclusive_write("startup maintenance", wait=True, busy_detail="Startup maintenance is already in progress."):
        create_all_started_at = perf_counter()
        Base.metadata.create_all(bind=engine)
        create_all_ms = (perf_counter() - create_all_started_at) * 1000

        schema_started_at = perf_counter()
        ensure_sqlite_upload_progress_columns()
        ensure_sqlite_alarm_hard_removal()
        schema_ms = (perf_counter() - schema_started_at) * 1000

        compaction_started_at = perf_counter()
        compacted_storage = ensure_sqlite_core_storage_compaction()
        compaction_ms = (perf_counter() - compaction_started_at) * 1000

        dedup_started_at = perf_counter()
        dedup_schema_changed = ensure_sqlite_upload_dedup_schema()
        dedup_ms = (perf_counter() - dedup_started_at) * 1000

        stale_count = 0
        duplicate_count = 0
        purged_count = 0
        expired_stage_count = 0
        stale_processing_ms = 0.0
        duplicate_purge_ms = 0.0
        stale_orphan_purge_ms = 0.0
        expired_stage_purge_ms = 0.0
        archival_ms = 0.0
        archived_upload_count = 0

        with SessionLocal() as db:
            bootstrap_ms = 0.0
            expired_session_count = 0
            expired_session_ms = 0.0
            if not settings.is_local_app:
                bootstrap_started_at = perf_counter()
                ensure_bootstrap_user(db)
                bootstrap_ms = (perf_counter() - bootstrap_started_at) * 1000

                expired_session_started_at = perf_counter()
                expired_session_count = purge_expired_sessions(db)
                expired_session_ms = (perf_counter() - expired_session_started_at) * 1000
                if expired_session_count > 0:
                    logger.info("Purged %d expired user sessions on startup", expired_session_count)

            stale_processing_started_at = perf_counter()
            stale_count = fail_stale_processing_uploads(db)
            stale_processing_ms = (perf_counter() - stale_processing_started_at) * 1000
            if stale_count > 0:
                logger.warning("Marked %d stale processing uploads as error on startup", stale_count)

            duplicate_purge_started_at = perf_counter()
            duplicate_count = purge_duplicate_orphan_uploads(db)
            duplicate_purge_ms = (perf_counter() - duplicate_purge_started_at) * 1000
            if duplicate_count > 0:
                logger.info("Purged %d duplicate orphan uploads on startup", duplicate_count)

            stale_orphan_purge_started_at = perf_counter()
            purged_count = purge_stale_orphan_uploads(db)
            stale_orphan_purge_ms = (perf_counter() - stale_orphan_purge_started_at) * 1000
            if purged_count > 0:
                logger.info("Purged %d orphaned uploads on startup", purged_count)

            archival_started_at = perf_counter()
            archived_upload_count = len(run_archival(db, actor="system"))
            archival_ms = (perf_counter() - archival_started_at) * 1000
            if archived_upload_count > 0:
                logger.info("Archived %d completed uploads on startup", archived_upload_count)

        expired_stage_started_at = perf_counter()
        expired_stage_count = purge_expired_staged_uploads()
        expired_stage_purge_ms = (perf_counter() - expired_stage_started_at) * 1000
        if expired_stage_count > 0:
            logger.info("Purged %d expired staged uploads on startup", expired_stage_count)

    update_check_started_at = perf_counter()
    update_status = refresh_update_status(force=True)
    update_check_ms = (perf_counter() - update_check_started_at) * 1000
    if update_status.get("is_update_available"):
        logger.info(
            "Software update available current_version=%s latest_version=%s download_url=%s",
            APP_VERSION,
            update_status.get("latest_version"),
            update_status.get("download_url"),
        )

    logger.info(
        "Startup completed create_all_ms=%.2f schema_ms=%.2f compaction_ms=%.2f dedup_ms=%.2f bootstrap_ms=%.2f expired_session_ms=%.2f stale_processing_ms=%.2f duplicate_purge_ms=%.2f stale_orphan_purge_ms=%.2f archival_ms=%.2f expired_stage_purge_ms=%.2f update_check_ms=%.2f total_ms=%.2f compacted_storage=%s dedup_schema_changed=%s expired_sessions=%s stale_processing=%s duplicate_orphans=%s stale_orphans=%s archived_uploads=%s expired_stages=%s",
        create_all_ms,
        schema_ms,
        compaction_ms,
        dedup_ms,
        bootstrap_ms,
        expired_session_ms,
        stale_processing_ms,
        duplicate_purge_ms,
        stale_orphan_purge_ms,
        archival_ms,
        expired_stage_purge_ms,
        update_check_ms,
        (perf_counter() - startup_started_at) * 1000,
        compacted_storage,
        dedup_schema_changed,
        expired_session_count,
        stale_count,
        duplicate_count,
        purged_count,
        archived_upload_count,
        expired_stage_count,
    )
    try:
        yield
    finally:
        runtime_lock.release()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)


@app.exception_handler(ExclusiveWriteBusyError)
async def exclusive_write_busy_handler(_: Request, exc: ExclusiveWriteBusyError):
    return JSONResponse(status_code=409, content={"detail": exc.detail})


@app.exception_handler(SQLiteBusyError)
async def sqlite_busy_handler(_: Request, exc: SQLiteBusyError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})

if settings.cors_origin_list and not settings.is_local_app:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", settings.csrf_header_name],
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    set_request_id(request_id)
    started_at = perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (perf_counter() - started_at) * 1000
        response.headers.setdefault("X-Request-ID", request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        logger.info(
            "Request completed",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        return response
    finally:
        set_request_id(None)


protected_dependencies = [] if settings.is_local_app else [Depends(require_active_user), Depends(enforce_csrf)]

if not settings.is_local_app:
    app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(patients.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(staged_uploads.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(uploads.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(decode.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(encounters.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(sessions.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(export.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(settings_router.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(database_stats.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(archives.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(audit.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(updates.router, prefix=settings.api_prefix, dependencies=protected_dependencies)
app.include_router(telemetry.router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


if settings.is_local_app:
    @app.get("/", include_in_schema=False)
    async def local_app_index() -> FileResponse:
        index_path = _frontend_index_path()
        if index_path is None:
            raise HTTPException(status_code=503, detail="Frontend assets are not available.")
        return FileResponse(index_path)


    @app.get("/{full_path:path}", include_in_schema=False)
    async def local_app_spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/") or full_path == "health":
            raise HTTPException(status_code=404, detail="Not found")

        if full_path:
            static_file = _frontend_file_path(full_path)
            if static_file is not None:
                return FileResponse(static_file)

        index_path = _frontend_index_path()
        if index_path is None:
            raise HTTPException(status_code=503, detail="Frontend assets are not available.")
        return FileResponse(index_path)

