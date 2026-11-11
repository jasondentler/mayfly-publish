"""Stateless transfer to a short-lived private S3 object."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from .errors import PublishError
from .local_files import open_file
from .settings import Settings
from .storage import MANAGED_NAME, Storage

log = logging.getLogger(__name__)


class Publisher:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage

    def temp_publish(
        self, relative_path: str, ttl_seconds: int | None = None, content_type: str | None = None
    ) -> dict[str, object]:
        ttl = self.settings.ttl if ttl_seconds is None else ttl_seconds
        if not 300 <= ttl <= 86400:
            raise PublishError("invalid_input", "ttl_seconds must be 300–86400")
        source = open_file(self.settings.file_root, relative_path, self.settings.max_file_bytes, content_type)
        with source.stream:
            staging_id = str(uuid.uuid4())
            key = self.settings.prefix + staging_id
            try:
                self.storage.upload(key, source.stream, source.content_type)
                source.ensure_unchanged()
                head = self.storage.head(key)
                if (
                    head is None
                    or int(cast(int, head["ContentLength"])) != source.size_bytes
                    or head.get("ContentType") != source.content_type
                ):
                    raise PublishError("upload_incomplete", "Remote object did not match the source")
                url = self.storage.sign_get(key, ttl)
            except Exception:
                try:
                    self.storage.delete(key)
                except PublishError:
                    log.warning("partial_object_cleanup_failed staging_id=%s", staging_id)
                raise
            expires = (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat()
            log.info("transfer_ready staging_id=%s size_bytes=%d", staging_id, source.size_bytes)
            return {
                "staging_id": staging_id,
                "url": url,
                "url_expires_at": expires,
                "content_type": source.content_type,
                "size_bytes": source.size_bytes,
                "status": "ready",
            }

    def revoke_object(self, staging_id: str) -> dict[str, str]:
        if not MANAGED_NAME.fullmatch(staging_id):
            raise PublishError("invalid_input", "Invalid staging_id")
        key = self.settings.prefix + staging_id
        self.storage.delete(key)
        if self.storage.head(key) is not None:
            raise PublishError("storage_unavailable", "Remote deletion is not yet confirmed; retry")
        log.info("transfer_revoked staging_id=%s", staging_id)
        return {"staging_id": staging_id, "status": "revoked"}
