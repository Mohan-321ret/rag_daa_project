"""
Cleanup Service
---------------
Responsible for safely deleting temporary uploaded files from disk.
This is always called AFTER successful text extraction AND database storage.
No uploaded document should remain on disk.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class CleanupService:
    """Handles deletion of temporary files after successful processing."""

    @staticmethod
    def delete_temp_file(file_path: str | Path) -> bool:
        """
        Delete the temporary file at *file_path*.

        Returns True if the file was deleted, False if it didn't exist.
        Raises RuntimeError if deletion fails for any other reason.
        """
        path = Path(file_path)

        if not path.exists():
            logger.warning(
                "[CleanupService] Temp file not found (already deleted?): %s",
                path,
            )
            return False

        try:
            path.unlink()
            logger.info(
                "[CleanupService] ✅ Temporary file deleted: %s",
                path.name,
            )
            return True
        except OSError as exc:
            logger.error(
                "[CleanupService] ❌ Failed to delete temp file %s: %s",
                path,
                exc,
            )
            raise RuntimeError(
                f"Could not delete temporary file '{path}': {exc}"
            ) from exc

    @staticmethod
    def safe_delete(file_path: str | Path) -> None:
        """
        Best-effort deletion – logs errors but does NOT raise.
        Use this in exception handlers where we still want to clean up
        without masking the original error.
        """
        try:
            CleanupService.delete_temp_file(file_path)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[CleanupService] safe_delete suppressed error: %s", exc
            )
