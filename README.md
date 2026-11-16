# Mayfly Publish

![Mayfly Publish logo](docs/assets/mayfly-publish-logo.png)

Mayfly Publish is a stateless MCP server that previews local JPEGs and MP4s, and can transfer a user-selected local file to private S3-compatible storage for a temporary HTTPS GET URL. The server runs over stdio and is independent of the calling MCP client, storage provider, and URL recipient.

## Install

Requirements: [uv](https://docs.astral.sh/uv/), `tunnel-client`, an existing private S3-compatible bucket, and macOS or Linux. Local previews require `ffmpeg` and `ffprobe` on `PATH`; metadata requires `exiftool`. `make setup` installs the latest available Python 3.15 patch release (at least 3.15.2) and project dependencies.

```sh
make setup
make serve
```

`make setup` asks for the file directory, storage settings and credentials, tunnel runtime key, and an existing tunnel ID. It stores account settings and secrets in the OS keyring, writes generic references to a mode-`0600` `.env`, and initializes the tunnel profile. Existing settings are retained. It ends with `Next: make serve`.

Keep the bucket private. Use object read/write credentials that include listing; bucket administration is not needed. The app does not create buckets or lifecycle rules.

| Variable | Purpose |
| --- | --- |
| `FILE_ROOT` | Existing readable root for selectable files; default `~/ToPublish`. Tool paths are relative to it. |
| `S3_ENDPOINT` or `S3_ENDPOINT_KEYRING_SERVICE` | HTTPS endpoint of the S3-compatible API, including any required path; setup uses a keyring reference. |
| `S3_REGION`, `S3_BUCKET` or `S3_BUCKET_KEYRING_SERVICE`, `S3_PREFIX` | Signing region, private bucket, and managed object prefix (default `mayfly-staging/`); setup stores the bucket name in the keyring. |
| `S3_ADDRESSING_STYLE` | `path` (default), `virtual`, or `auto`, according to the provider's S3 API. |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Bucket-scoped credentials from `.env` or process environment. |
| `S3_ACCESS_KEY_ID_KEYRING_SERVICE`, `S3_SECRET_ACCESS_KEY_KEYRING_SERVICE` | System keyring service names; each replaces the corresponding plaintext value. |
| `SIGNED_URL_TTL_SECONDS` | Default 7200; per-call allowed range 300–86400 seconds. |
| `MAX_FILE_BYTES` | Default 100 MiB; configurable positive limit on one synchronous upload. |
| `STAGED_OBJECT_MAX_AGE_HOURS` | Default and minimum 25; cleanup waits beyond the maximum 24-hour URL TTL. |
| `LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, or `ERROR`; application logs go to stderr. |

Keyring service references take precedence over plaintext values; other process environment settings override `.env`. The file is ignored by Git and must have mode `0600`. `make keyring-set` prompts again for both S3 credentials if they need replacing. The [keyring library](https://keyring.readthedocs.io/en/stable/) selects the OS backend; an unavailable keyring stops startup. Keep credentials and signed URLs out of chat, Git, and shell history.

## Architecture and security

```text
MCP client → local stdio Mayfly Publish → private S3-compatible bucket
MCP client → signed GET URL → chosen short-term recipient
MCP client → revoke_object after the temporary need ends
Local cleanup + provider lifecycle where available → remove abandoned objects
```

`preview_local_file` returns resized JPEG image content through MCP without uploading it to S3. For MP4s, it returns up to three still frames sampled across the clip; it does not play motion or audio. Previews are at most 960 pixels on either side and 2 MB per image. `temp_publish` sends the original file directly from the host to the configured private bucket. The server opens no HTTP listener or inbound port. A signed URL is a bearer credential: anyone holding it can fetch the object until it expires or the object is deleted.

`get_local_metadata` returns ExifTool-readable tags directly through MCP, without uploading. Metadata can include GPS coordinates and other sensitive information. Source path fields are removed; embedded tag values are returned as ExifTool reports them. Binary media payloads are not included.

The server accepts any regular file type beneath `FILE_ROOT`, including extensionless files, and rejects traversal, symlinks, and oversized files. The file listing shows only folders and files with `.jpg`, `.jpeg`, or `.mp4` extensions (case insensitive), and skips hidden entries, symlinks, special files, and files over `MAX_FILE_BYTES`. It does not inspect file bytes to verify the format. It never rewrites the source. Storage requests use TLS and SigV4; an upload is reported ready only after remote verification.

Objects use generated names under `S3_PREFIX`. Logs omit local paths, credentials, signed URLs, and file content; MCP stdout contains protocol messages only. See the [implementation plan](docs/implementation-plan.md) for the detailed transport and security contract.

## MCP tools

| Tool | Inputs | Output |
| --- | --- | --- |
| `list_local_files` | None | Sorted `files` and `folders` arrays of paths relative to `FILE_ROOT`, including nested paths. Only JPEG and MP4 filename extensions are listed; files over `MAX_FILE_BYTES` are omitted. |
| `preview_local_file` | `relative_path` | Local image preview for JPEGs or up to three sampled still frames for MP4s; no S3 upload. |
| `get_local_metadata` | `relative_path` | Grouped ExifTool tags for a JPEG or MP4, including embedded and unknown tags where available; no S3 upload. |
| `temp_publish` | `relative_path`, optional `ttl_seconds`, optional `content_type` | New private object; `staging_id`, `url`, `url_expires_at`, `content_type`, `size_bytes`, `status`. Every call creates a new object. |
| `revoke_object` | `staging_id` | Deletes the matching temporary object and returns `revoked`; repeated calls are safe. |

If the recipient requires a specific MIME type, pass `content_type` (for example, `application/pdf`). Otherwise the server guesses from the filename and uses `application/octet-stream` for unknown types. The upload and revoke tools declare MCP write annotations, so a client may request confirmation.

1. Call `list_local_files` to find a relative path, or give the MCP client the relative path of a file under `FILE_ROOT`. Use `preview_local_file` to inspect a JPEG or MP4 and `get_local_metadata` to read its tags.
2. When a URL is needed, call `temp_publish` with the path and, if needed, `content_type` and TTL.
3. Give the returned URL to the chosen recipient while it is valid. Treat the URL as a secret.
4. When the recipient no longer needs the temporary object, call `revoke_object(staging_id)`.

URL expiration does not delete the object. Each `temp_publish` call creates a separate object and URL.

## Optional OpenAI Secure MCP Tunnel

Any compatible local MCP client can launch `scripts/run-mcp.sh` over stdio. `make serve` starts OpenAI Secure MCP Tunnel and its MCP child using the profile created by `make setup`. Obtain the tunnel ID and a restricted runtime key before setup; see the [tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). Run `make tunnel-doctor` to check the profile, then connect your OpenAI client and confirm discovery of all five MCP tools.

`make serve` stops both processes after one hour. Override that with `make serve LIFETIME_SECONDS=7200`; the allowed range is 1–86400 seconds, with no unlimited mode. The host must remain awake and online while serving.

## Lifecycle and recovery

Run `make cleanup-dry-run` to count expired managed objects, or `.venv/bin/mayfly-publish cleanup` to delete them. Cleanup waits at least 25 hours after upload. On macOS, `scripts/install-launchd-cleanup.sh` schedules it hourly; on Linux, schedule the same CLI with your preferred service manager. Where supported, add a provider lifecycle rule scoped to `S3_PREFIX` as a fallback. Keep local cleanup scheduled if the provider has no lifecycle rules.

If upload verification fails, no ready URL is returned and remote deletion is attempted. A retry creates a new object; retain its staging ID for later revocation.

## Development and testing

```sh
make check
make smoke
make install-git-hooks
```

`make check` runs Ruff, mypy, and pytest; `make fmt` applies formatting. `make install-git-hooks` enables the Conventional Commits hook. Tests use synthetic credentials and a local fake S3 service; they do not contact cloud storage or use account URLs.

## Platform boundaries

- **macOS and Linux:** Supported for serving and cleanup; use an unlocked OS keyring session.
- **Windows:** Not supported by the current file access and launcher scripts.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Startup `configuration` error | `.env` mode `0600`, required values, HTTPS endpoint, readable `FILE_ROOT`, retention at least 25 hours. |
| File access denied | Grant the terminal or process read permission for the configured folder. On macOS, check Privacy settings for protected folders. |
| System keyring credential unavailable | Check the service name, fixed username `mayfly-publish`, and OS keyring session. On Ubuntu, Secret Service needs an unlocked keyring and D-Bus session; headless sessions need additional setup. |
| `invalid_input` or `file_unavailable` | Use a relative path beneath `FILE_ROOT`; avoid hidden components and symlinks. |
| Wrong `Content-Type` at recipient | Pass an explicit `content_type` supported by the recipient; Mayfly Publish does not inspect bytes. |
| Upload or signed GET fails | Check bucket privacy, credential scope, endpoint, region, addressing style, and connectivity. |
| Tunnel discovery fails | Run `make tunnel-doctor` and check client status. |
