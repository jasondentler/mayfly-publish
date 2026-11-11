"""Stateless cleanup based on S3 object age and a managed UUID prefix."""

import logging
from datetime import UTC, datetime, timedelta

from .errors import PublishError
from .settings import Settings
from .storage import Storage

log = logging.getLogger(__name__)


def cleanup(settings: Settings, storage: Storage, dry_run: bool = False) -> dict[str, int]:
    # Every publish may request up to 24 hours; one extra hour avoids deleting a live URL.
    minimum_age = timedelta(hours=max(settings.max_age_hours, 25))
    cutoff = datetime.now(UTC) - minimum_age
    eligible = deleted = failed = 0
    for key, last_modified in storage.list_staged():
        if last_modified > cutoff:
            continue
        eligible += 1
        if dry_run:
            continue
        try:
            storage.delete(key)
            if storage.head(key) is not None:
                raise PublishError("storage_unavailable", "Deletion not confirmed")
            deleted += 1
        except PublishError:
            failed += 1
            log.warning("cleanup_delete_failed")
    log.info("cleanup_complete eligible=%d deleted=%d failed=%d", eligible, deleted, failed)
    return {"eligible": eligible, "deleted": deleted, "failed": failed}
