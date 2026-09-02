"""
Document Change Monitor  –  Phase 6 Module 3 (Step 1)
-------------------------------------------------------
Watches for document changes from two directions:

  1. UPLOADED FILES – every upload passes through the evolution engine
     (evolution_service.process_document), which matches the incoming file
     against existing versions by filename + content hash.

  2. FOLDER CHANGES – a background watcher polls `settings.watch_dir`.
     New or modified files (with an allowed extension) are automatically
     ingested through the exact same evolution pipeline. A file is only
     picked up once its size/mtime is stable across two consecutive polls
     (so half-copied files are never ingested).

No external dependency (watchdog etc.) is required – plain asyncio polling
keeps this portable across Windows/Linux/Docker volumes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.services.document_loader import load_document
from app.services.metadata_service import build_document_metadata
from app.services.ocr_service import run_ocr_on_pdf
from app.utils.file_utils import (
    generate_document_id,
    get_extension,
    normalize_text,
    safe_filename,
    validate_extension,
    validate_file_size,
)

logger = logging.getLogger(__name__)


# ── Ingest a file straight from disk (used by the folder watcher) ─────────────

def ingest_path(path: Path, source: str = "watcher") -> dict:
    """
    Run the full ingestion + evolution pipeline for a file on disk.

    Mirrors the /documents/upload flow (validation → extraction → OCR
    fallback → metadata → evolution-aware processing) but works without an
    HTTP request, using its own DB session.

    Returns the evolution summary dict from evolution_service.process_document.
    Raises ValueError / RuntimeError on validation or extraction failures.
    """
    validate_extension(path.name)
    validate_file_size(path.stat().st_size)

    document_id = generate_document_id()
    ext = get_extension(path.name)
    safe_name = safe_filename(path.name, document_id)

    # ── Text extraction with OCR fallback (same as upload endpoint) ──────────
    raw_text, extraction_duration_s = load_document(path)
    ocr_used = False
    if ext == ".pdf" and not raw_text.strip():
        logger.info("[ChangeMonitor] PDF has no text layer – running OCR: %s", path.name)
        raw_text, extraction_duration_s = run_ocr_on_pdf(path)
        ocr_used = True

    if not raw_text.strip():
        raise RuntimeError(f"No text could be extracted from '{path.name}'.")

    clean = normalize_text(raw_text)

    doc_data = build_document_metadata(
        document_id=document_id,
        original_filename=path.name,
        filename=safe_name,
        file_extension=ext,
        extracted_text=clean,
        ocr_used=ocr_used,
        extraction_duration_s=extraction_duration_s,
        file_path=path,
    )

    from app.services.evolution_service import process_document

    db = SessionLocal()
    try:
        summary = process_document(db, doc_data, source=source)
        # Extract plain values BEFORE the session closes – the ORM object
        # becomes detached afterwards and attribute access would fail.
        doc = summary.get("document")
        return {
            "action": summary.get("action"),
            "event_id": summary.get("event_id"),
            "document_id": doc.document_id if doc is not None else None,
            "version": doc.version if doc is not None else None,
            "chunk_count": summary.get("chunk_count"),
            "evolution": summary.get("evolution"),
        }
    finally:
        db.close()


# ── Background folder watcher ─────────────────────────────────────────────────

class FolderWatcher:
    """
    Polls `settings.watch_dir` for new/changed documents and feeds them into
    the evolution pipeline. Files must be stable (same size + mtime) across
    two consecutive scans before they are ingested.
    """

    def __init__(self) -> None:
        self.watch_dir = Path(settings.watch_dir)
        self.poll_interval = max(2, settings.watch_poll_interval_s)
        self._ingested: dict[str, tuple[float, int]] = {}  # path → (mtime, size)
        self._pending: dict[str, tuple[float, int]] = {}   # path → last observed state
        self._task: Optional[asyncio.Task] = None
        self.running: bool = False
        self.last_scan: Optional[str] = None
        self.files_ingested: int = 0
        self.recent_events: list[dict] = []                # rolling log for the API

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Launch the polling loop as an asyncio background task."""
        if self.running:
            return False
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        # Treat files already present at startup as pending: they get ingested
        # once, and the evolution engine skips them if content is unchanged.
        self.running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "[ChangeMonitor] 👀 Folder watcher started | dir=%s interval=%ds",
            self.watch_dir.resolve(), self.poll_interval,
        )
        return True

    async def stop(self) -> bool:
        if not self.running:
            return False
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("[ChangeMonitor] 🛑 Folder watcher stopped.")
        return True

    async def _run(self) -> None:
        while self.running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[ChangeMonitor] Scan failed: %s", exc)
            await asyncio.sleep(self.poll_interval)

    # ── Scanning ─────────────────────────────────────────────────────────────

    def _current_files(self) -> dict[str, tuple[float, int]]:
        files: dict[str, tuple[float, int]] = {}
        if not self.watch_dir.exists():
            return files
        for p in self.watch_dir.iterdir():
            if p.is_file() and p.suffix.lower() in settings.allowed_ext_list:
                try:
                    st = p.stat()
                    files[str(p.resolve())] = (st.st_mtime, st.st_size)
                except OSError:
                    continue
        return files

    async def _scan_once(self) -> None:
        self.last_scan = datetime.now(timezone.utc).isoformat()
        snapshot = self._current_files()

        for path_str, state in snapshot.items():
            if self._ingested.get(path_str) == state:
                continue  # already processed in this exact state

            if self._pending.get(path_str) == state:
                # Stable across two polls → safe to ingest
                del self._pending[path_str]
                await self._ingest(Path(path_str), state)
            else:
                # First sighting (or still being written) → wait one more poll
                self._pending[path_str] = state

        # Forget bookkeeping for files that were deleted from the folder
        for path_str in list(self._ingested):
            if path_str not in snapshot:
                del self._ingested[path_str]
        for path_str in list(self._pending):
            if path_str not in snapshot:
                del self._pending[path_str]

    async def _ingest(self, path: Path, state: tuple[float, int]) -> None:
        logger.info("[ChangeMonitor] 📂 Change detected: %s", path.name)
        try:
            # Extraction + embedding are CPU/IO heavy → keep the loop responsive
            summary = await asyncio.to_thread(ingest_path, path, "watcher")
            self._ingested[str(path)] = state
            self.files_ingested += 1
            self._log_event({
                "file": path.name,
                "action": summary.get("action"),
                "document_id": summary.get("document_id"),
                "version": summary.get("version"),
                "event_id": summary.get("event_id"),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(
                "[ChangeMonitor] ✅ Ingested %s | action=%s doc=%s",
                path.name, summary.get("action"), summary.get("document_id"),
            )
        except Exception as exc:
            # Remember the failed state so we don't retry the same bytes forever
            self._ingested[str(path)] = state
            self._log_event({
                "file": path.name,
                "action": "error",
                "error": str(exc),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            logger.error("[ChangeMonitor] ❌ Failed to ingest %s: %s", path.name, exc)

    def _log_event(self, event: dict) -> None:
        self.recent_events.insert(0, event)
        del self.recent_events[50:]

    # ── Status (API) ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running": self.running,
            "watch_dir": str(self.watch_dir.resolve()),
            "poll_interval_s": self.poll_interval,
            "last_scan": self.last_scan,
            "files_tracked": len(self._ingested),
            "files_ingested": self.files_ingested,
            "recent_events": self.recent_events[:20],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_watcher: FolderWatcher | None = None


def get_folder_watcher() -> FolderWatcher:
    global _watcher
    if _watcher is None:
        _watcher = FolderWatcher()
    return _watcher
