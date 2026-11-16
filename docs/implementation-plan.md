# Mayfly Publish implementation plan

## Purpose and boundary

Mayfly Publish is a stateless, client-agnostic MCP server for local media preview, metadata, and temporary file transport. It previews JPEGs and MP4s, reads their ExifTool metadata, and can upload any regular file to a configured private S3-compatible bucket for a short-lived, direct HTTPS GET URL. It never edits, moves, or deletes the local source, and it never calls the recipient service.

Preview image content and embedded metadata may be used by the calling client to identify subjects and prepare editorial text. Filenames, folder names, and transport output must not be used for that purpose.

The MCP can list relative paths, return resized image previews, and read metadata under `FILE_ROOT`. It keeps no staging registry. Its temporary S3 objects are the only staging state.

## Architecture

```text
Calling MCP client → local stdio MCP → configured private S3-compatible bucket
Calling MCP client → ephemeral signed GET URL → chosen recipient
Calling MCP client → revoke_object when the temporary need ends
Scheduled local cleanup → managed S3 prefix → delete old objects
Provider lifecycle rule → fallback expiration
```

The server is a Python 3.15.2+ stdio MCP using the official Python SDK. A local client may launch it directly. `make setup` installs dependencies and gathers local configuration and keyring secrets; it ends by directing the user to `make serve`. `make serve` starts OpenAI Secure MCP Tunnel and its stdio MCP child with a one-hour default runtime and a command-line override capped at one day. No inbound HTTP listener is required.

The current secure file opener targets POSIX systems (macOS and Linux) through `O_DIRECTORY`, `O_NOFOLLOW`, and `dir_fd`. The Python `keyring` integration selects the available OS backend. The included `launchd` installer is macOS-only; Linux can schedule the same cleanup CLI with its own scheduler. Windows requires equivalent reparse-point-safe file access, shell/launcher replacements, and an ACL-based `.env` permission check before the full application can be supported there.

## Tools

### `list_local_files()`

- Return sorted `files` and `folders` arrays of relative paths under `FILE_ROOT`, including nested paths. List only `.jpg`, `.jpeg`, and `.mp4` files, matching extensions case insensitively. Skip hidden entries, symlinks, special files, files over `MAX_FILE_BYTES`, and paths too long for `temp_publish`. Do not return absolute paths or inspect contents.
- Treat paths as transport identifiers only; do not derive editorial content from them.

### `preview_local_file(relative_path)`

- Accept a relative JPEG or MP4 path under `FILE_ROOT` using the same secure file opener as upload. The extension check is case insensitive; FFmpeg decodes the bytes. No S3 operation occurs.
- Return one resized JPEG image for a still, or up to three JPEG still frames from an MP4 near its start, middle, and end. Limit each image to 960 pixels per side and 2 MB. Motion and audio are not returned.
- Require local `ffmpeg` and `ffprobe` executables. Run them with a restricted input protocol list and a timeout; avoid exposing paths or decoder errors in MCP responses.

### `get_local_metadata(relative_path)`

- Accept a relative JPEG or MP4 path under `FILE_ROOT` using the same secure file opener as upload. Run local ExifTool with group and copy identifiers, unknown tags, and embedded extraction enabled. No S3 operation occurs.
- Return all ExifTool-readable tags in a `metadata` object, excluding filesystem path fields. Embedded tag values may include sensitive information such as GPS coordinates. Binary media payloads are omitted. Reject extraction failures and responses over 10 MB rather than returning partial metadata.

### `temp_publish(relative_path, ttl_seconds=None, content_type=None)`

- The caller supplies a path relative to configured `FILE_ROOT`. The server rejects absolute paths, traversal, hidden components, symlinks, directories, special devices, and paths outside the root. File access uses `O_NOFOLLOW` and validates the open file's device, inode, size, and modification time before and after upload.
- Any regular file is supported, including extensionless, unknown-extension, binary, text, and zero-byte files. The server does not inspect or transform file bytes. `MAX_FILE_BYTES` (default 100 MiB) bounds one synchronous upload; it is a size limit, not a file-type restriction.
- `Content-Type` comes from a validated optional `content_type`, otherwise a filename-based MIME guess, otherwise `application/octet-stream`. This is transport metadata, not content analysis. The caller should supply `content_type` when a recipient requires a specific MIME type.
- Upload directly to the configured private bucket using a UUIDv4 object key under `S3_PREFIX`, without the original filename. Verify remote size and `Content-Type` with `HeadObject`. On failure, return no ready URL and attempt immediate deletion.
- Generate a read-only SigV4 GET URL with a 300–86400 second TTL (default two hours). Return only `staging_id`, `url`, `url_expires_at`, `content_type`, `size_bytes`, and `status`. Every call makes a new temporary object.

### `revoke_object(staging_id)`

- Accept only a UUIDv4 staging ID. Construct the object key under the configured prefix; never accept a caller-supplied bucket or arbitrary key.
- Delete and confirm absence. Repeated calls are idempotent. The local source remains untouched.

## Configuration, security, and logging

Configuration comes from a mode-`0600` `.env` file and/or process environment. Require an existing readable `FILE_ROOT`, HTTPS `S3_ENDPOINT`, region, bucket, managed prefix, credentials, valid TTL, and positive file size/retention limits. `S3_ADDRESSING_STYLE` supports `path`, `virtual`, and `auto` for provider compatibility. Use SigV4 and TLS verification. Setup stores the endpoint, bucket name, and credentials in the OS system keyring through the Python `keyring` library; `.env` contains only generic service references and non-account defaults. An unavailable backend fails closed. Never log credentials, full signed URLs, or local paths, and never write them to project files. The listing tool returns relative paths only. MCP stdout is protocol-only; application logs go to stderr and contain safe event names, staging IDs, sizes, counts, and error codes.

Use a private bucket and prefer a dedicated object read/write credential scoped to it where the provider supports that scope. Bucket creation, credential issuance, and lifecycle configuration are manual setup steps. Do not provision resources or use real credentials without user approval.
The runtime requires only `PutObject`, `HeadObject`, `DeleteObject`, and `ListObjectsV2` permissions; signing a presigned `GetObject` URL is local. A bucket-scoped object read/write token with listing is sufficient where available. No bucket create/list/configure API is called by Mayfly Publish. Allow safe path components in `S3_ENDPOINT` for S3-compatible APIs that require them. Keep credentials in distinct OS keyring services and restrict the configured bucket and prefix.

## Ephemeral lifecycle

Signed URL expiry does not delete the object. Explicit `revoke_object` ends access early. An independent `mayfly-publish cleanup [--dry-run]` CLI lists objects under the managed S3 prefix and deletes only UUIDv4-named objects older than `STAGED_OBJECT_MAX_AGE_HOURS`, default and minimum 25 hours. This exceeds the maximum signed URL lifetime by one hour. A per-user `launchd` job can run cleanup hourly. Configure a provider lifecycle rule scoped to the managed prefix for a 2–3 day fallback and incomplete multipart cleanup where available. Keep scheduled local cleanup enabled where bucket lifecycle rules are unavailable. Never configure bucket-wide deletion that could affect unrelated data.

## Testing and acceptance

- Ruff lint/format, strict mypy, and pytest pass without real credentials or cloud resources.
- A stdio MCP handshake exposes exactly `list_local_files`, `preview_local_file`, `get_local_metadata`, `temp_publish`, and `revoke_object`.
- Tests cover arbitrary binary/text/extensionless/empty files, safe path handling, MIME override validation, size limits, source-change detection, upload verification, SigV4 GET signing, idempotent revoke, managed-key cleanup, system keyring references, and safe logs.
- Listing responses contain relative paths only. Preview responses contain reduced image content, and metadata responses contain ExifTool tags. No upload response contains source content, original filename, editorial fields, credentials, or authentication headers. No local source file is changed.
- A manual integration check uses a disposable file and user-approved storage credentials: verify a signed URL from an unauthenticated client, verify response content type and length, revoke it, and confirm the source hash is unchanged. Recipient-specific testing is optional and outside the MCP contract.

## References

- [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Tunnel client onboarding](https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md)
- [Tunnel client configuration](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)
