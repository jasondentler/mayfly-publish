"""Stdio MCP tools for local preview and temporary file transport."""

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ToolAnnotations

from .errors import PublishError
from .local_files import list_files
from .metadata import read_local_metadata
from .preview import preview_local_file as make_preview
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
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    )
    def list_local_files() -> dict[str, object]:
        """List relative JPEG, MP4, and folder paths beneath FILE_ROOT, including nested paths.

        Paths identify available files only. Never use filenames or folder names for
        captions, descriptions, alt text, hashtags, or subject identification.
        """
        return safe(list_files, settings.file_root, settings.max_file_bytes)

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    )
    def preview_local_file(relative_path: str) -> Any:
        """Show a local JPEG image or sampled MP4 still frames without uploading.

        Preview content may be used to identify subjects and prepare editorial text.
        """
        try:
            return make_preview(settings, relative_path)
        except PublishError as exc:
            log.warning("tool_failed code=%s", exc.code)
            return [TextContent(type="text", text=json.dumps(exc.as_dict()))]
        except Exception:
            log.error("tool_failed code=internal_error")
            return [TextContent(type="text", text='{"error":"internal_error","message":"Preview failed"}')]

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    )
    def get_local_metadata(relative_path: str) -> dict[str, object]:
        """Return ExifTool tags from a local JPEG or MP4 without uploading it.

        The result may contain sensitive embedded metadata, including GPS coordinates.
        """
        return safe(read_local_metadata, settings, relative_path)

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
