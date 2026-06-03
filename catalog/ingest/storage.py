"""Idempotent R2 backfill. Generic (no BCSD knowledge): the caller supplies the
already-computed key. No-ops when storage is the local filesystem fallback so
offline dev/CI never touch the network."""

import logging

from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage

logger = logging.getLogger(__name__)


def upload_missing(r2_key: str, local_path: str) -> bool:
    """Upload local_path to r2_key only if the object is absent. Returns True iff
    bytes were uploaded."""
    if isinstance(default_storage, FileSystemStorage):
        logger.debug("Filesystem storage fallback; skipping upload of %s", r2_key)
        return False
    if default_storage.exists(r2_key):
        return False
    with open(local_path, "rb") as fh:
        default_storage.save(r2_key, File(fh))
    logger.info("Uploaded missing object to R2: %s", r2_key)
    return True
