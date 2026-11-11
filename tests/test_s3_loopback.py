"""Real HTTP round-trip against a loopback-only fake S3 service."""

import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import ProxyHandler, build_opener
from xml.sax.saxutils import escape

import pytest

from mayfly_publish.cleanup import cleanup
from mayfly_publish.settings import Settings
from mayfly_publish.staging import Publisher
from mayfly_publish.storage import Storage

BUCKET_PATH = "/api/s3/test-bucket"


class FakeS3Server(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FakeS3Handler)
        self.objects: dict[str, tuple[bytes, str, datetime]] = {}


class FakeS3Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def objects(self) -> dict[str, tuple[bytes, str, datetime]]:
        assert isinstance(self.server, FakeS3Server)
        return self.server.objects

    def _key(self) -> str | None:
        path = unquote(urlsplit(self.path).path)
        if not path.startswith(BUCKET_PATH + "/"):
            self._respond(404)
            return None
        return path[len(BUCKET_PATH) + 1 :]

    def _respond(self, status: int, body: bytes = b"", content_type: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if content_type:
            self.send_header("Content-Type", content_type)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_PUT(self) -> None:
        key = self._key()
        if key is None:
            return
        size = int(self.headers.get("Content-Length", "0"))
        self.objects[key] = (
            self.rfile.read(size),
            self.headers.get("Content-Type", "application/octet-stream"),
            datetime.now(UTC),
        )
        self._respond(200)

    def do_HEAD(self) -> None:
        key = self._key()
        if key is None:
            return
        item = self.objects.get(key)
        if item is None:
            self._respond(404)
            return
        body, content_type, _ = item
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def do_DELETE(self) -> None:
        key = self._key()
        if key is not None:
            self.objects.pop(key, None)
            self._respond(204)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == BUCKET_PATH and query.get("list-type") == ["2"]:
            prefix = query.get("prefix", [""])[0]
            contents = "".join(
                '<Contents><Key>{}</Key><LastModified>{}</LastModified><ETag>"fake"</ETag>'
                "<Size>{}</Size><StorageClass>STANDARD</StorageClass></Contents>".format(
                    escape(key), modified.strftime("%Y-%m-%dT%H:%M:%S.000Z"), len(body)
                )
                for key, (body, _, modified) in self.objects.items()
                if key.startswith(prefix)
            )
            xml = (
                '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                f"<Name>test-bucket</Name><Prefix>{escape(prefix)}</Prefix><MaxKeys>1000</MaxKeys>"
                f"<IsTruncated>false</IsTruncated>{contents}</ListBucketResult>"
            ).encode()
            self._respond(200, xml, "application/xml")
            return
        key = self._key()
        if key is None:
            return
        if query.get("X-Amz-Algorithm") != ["AWS4-HMAC-SHA256"] or "X-Amz-Signature" not in query:
            self._respond(403)
            return
        item = self.objects.get(key)
        if item is None:
            self._respond(404)
            return
        self._respond(200, item[0], item[1])

    def log_message(self, format: str, *args: object) -> None:
        pass  # Signed query strings must never appear in test output.


def test_publish_get_revoke_and_cleanup_using_loopback_s3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        server = FakeS3Server()
    except PermissionError:
        pytest.skip("This sandbox does not permit binding a loopback test server")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    try:
        source = tmp_path / "arbitrary.bin"
        source.write_bytes(b"\x00arbitrary\xff")
        config = Settings(
            tmp_path,
            f"http://127.0.0.1:{server.server_port}/api/s3",
            "test-region-1",
            "test-bucket",
            "fake-access",
            "fake-secret",
            "mayfly-staging/",
            "path",
            7200,
            1000,
            25,
            "INFO",
        )
        storage = Storage(config)
        publisher = Publisher(config, storage)
        first = publisher.temp_publish("arbitrary.bin", content_type="application/octet-stream")
        url = str(first["url"])
        assert urlsplit(url).hostname == "127.0.0.1"
        assert urlsplit(url).path.startswith(BUCKET_PATH + "/mayfly-staging/")
        with build_opener(ProxyHandler({})).open(url) as response:
            assert response.read() == source.read_bytes()
        assert publisher.revoke_object(str(first["staging_id"]))["status"] == "revoked"
        with pytest.raises(HTTPError) as error:
            build_opener(ProxyHandler({})).open(url)
        assert error.value.code == 404

        second = publisher.temp_publish("arbitrary.bin")
        key = f"mayfly-staging/{second['staging_id']}"
        assert [item[0] for item in storage.list_staged()] == [key]
        body, content_type, _ = server.objects[key]
        server.objects[key] = (body, content_type, datetime.now(UTC) - timedelta(hours=26))
        assert cleanup(config, storage, dry_run=True) == {"eligible": 1, "deleted": 0, "failed": 0}
        assert cleanup(config, storage) == {"eligible": 1, "deleted": 1, "failed": 0}
        assert not server.objects
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
