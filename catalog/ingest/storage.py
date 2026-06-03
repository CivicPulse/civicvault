"""Idempotent R2 backfill. Generic (no BCSD knowledge): the caller supplies the
already-computed key. No-ops when storage is the local filesystem fallback so
offline dev/CI never touch the network."""

import logging
from pathlib import Path

from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage

logger = logging.getLogger(__name__)


def upload_missing(r2_key: str, local_path: str | Path) -> bool:
    """Upload local_path to r2_key only if the object is absent. Returns True iff
    bytes were uploaded."""
    # build_storages() only ever produces FileSystemStorage (no R2_BUCKET) or
    # S3Storage (bucket set), so this isinstance check is an exhaustive test for
    # "no real remote storage". Revisit if a new storage backend is introduced.
    if isinstance(default_storage, FileSystemStorage):
        logger.debug("Filesystem storage fallback; skipping upload of %s", r2_key)
        return False
    if default_storage.exists(r2_key):
        return False
    with open(local_path, "rb") as fh:
        # save() returns the stored name; we don't need it (the key is deterministic).
        default_storage.save(r2_key, File(fh))
    logger.info("Uploaded missing object to R2: %s", r2_key)
    return True
