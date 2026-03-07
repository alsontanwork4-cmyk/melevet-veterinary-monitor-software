from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import (
    Base,
    SessionLocal,
    engine,
    ensure_sqlite_core_storage_compaction,
    ensure_sqlite_upload_dedup_schema,
    ensure_sqlite_upload_progress_columns,
)
from .routers import alarms, decode, encounters, export, patients, sessions, uploads
from .services.upload_service import (
    fail_stale_processing_uploads,
    purge_duplicate_orphan_uploads,
    purge_stale_orphan_uploads,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_started_at = perf_counter()

    create_all_started_at = perf_counter()
    Base.metadata.create_all(bind=engine)
    create_all_ms = (perf_counter() - create_all_started_at) * 1000

    schema_started_at = perf_counter()
    ensure_sqlite_upload_progress_columns()
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
    stale_processing_ms = 0.0
    duplicate_purge_ms = 0.0
    stale_orphan_purge_ms = 0.0

    with SessionLocal() as db:
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

    logger.info(
        "Startup completed create_all_ms=%.2f schema_ms=%.2f compaction_ms=%.2f dedup_ms=%.2f stale_processing_ms=%.2f duplicate_purge_ms=%.2f stale_orphan_purge_ms=%.2f total_ms=%.2f compacted_storage=%s dedup_schema_changed=%s stale_processing=%s duplicate_orphans=%s stale_orphans=%s",
        create_all_ms,
        schema_ms,
        compaction_ms,
        dedup_ms,
        stale_processing_ms,
        duplicate_purge_ms,
        stale_orphan_purge_ms,
        (perf_counter() - startup_started_at) * 1000,
        compacted_storage,
        dedup_schema_changed,
        stale_count,
        duplicate_count,
        purged_count,
    )
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patients.router, prefix=settings.api_prefix)
app.include_router(uploads.router, prefix=settings.api_prefix)
app.include_router(decode.router, prefix=settings.api_prefix)
app.include_router(encounters.router, prefix=settings.api_prefix)
app.include_router(sessions.router, prefix=settings.api_prefix)
app.include_router(alarms.router, prefix=settings.api_prefix)
app.include_router(export.router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

