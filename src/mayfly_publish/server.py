"""Minimal stdio MCP transport contracts; no editorial metadata tools."""

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .errors import PublishError
from .settings import Settings
from .staging import Publisher
from .storage import Storage

log = logging.getLogger(__name__)


def create_server(settings: Settings, storage: Storage | None = None) -> FastMCP:
    publisher = Publisher(settings, storage or Storage(settings))
    mcp = FastMCP("Mayfly Publish")

    def safe(call: Any, *args: Any, **kwargs: Any) -> dict[str, object]:
        try:
            result: dict[str, object] = call(*args, **kwargs)
            return result
        except PublishError as exc:
            log.warning("tool_failed code=%s", exc.code)
            return dict(exc.as_dict())
        except Exception:
            log.error("tool_failed code=internal_error")
            return {"error": "internal_error", "message": "Operation failed; see local diagnostics"}

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        )
    )
    def temp_publish(
        relative_path: str, ttl_seconds: int | None = None, content_type: str | None = None
    ) -> dict[str, object]:
        """Transfer a user-identified local file to private S3 for ephemeral URL use.

        Never use this tool's output for captions, descriptions, alt text, hashtags,
        or subject identification. Editorial content comes only from material given
        directly to the calling client by the user.
        """
        return safe(publisher.temp_publish, relative_path, ttl_seconds, content_type)

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
    )
    def revoke_object(staging_id: str) -> dict[str, object]:
        """Delete one temporary S3 object when its short-lived use is complete."""
        return safe(publisher.revoke_object, staging_id)

    return mcp
