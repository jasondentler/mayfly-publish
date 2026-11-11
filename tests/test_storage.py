import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.stub import ANY, Stubber

from mayfly_publish.errors import PublishError
from mayfly_publish.settings import Settings
from mayfly_publish.storage import Storage


def test_s3_upload_head_sign_delete(tmp_path: Path) -> None:
    config = Settings(
        tmp_path,
        "https://storage.example.invalid",
        "us-east-1",
        "bucket",
        "access",
        "secret",
        "mayfly-staging/",
        "path",
        7200,
        1000,
        25,
        "INFO",
    )
    storage = Storage(config)
    key = f"mayfly-staging/{uuid.uuid4()}"
    with Stubber(storage.client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "bucket",
                "Key": key,
                "Body": ANY,
                "ContentType": "application/octet-stream",
            },
        )
        stub.add_response(
            "head_object",
            {"ContentLength": 3, "ContentType": "application/octet-stream"},
            {"Bucket": "bucket", "Key": key},
        )
        stub.add_response("delete_object", {}, {"Bucket": "bucket", "Key": key})
        storage.upload(key, BytesIO(b"abc"), "application/octet-stream")
        assert storage.head(key) == {"ContentLength": 3, "ContentType": "application/octet-stream"}
        parsed = urlparse(storage.sign_get(key, 7200))
        assert parsed.scheme == "https"
        assert parsed.hostname == "storage.example.invalid"
        assert parse_qs(parsed.query)["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        storage.delete(key)
    with pytest.raises(PublishError):
        storage.delete("backup/private")


def test_inventory_filters_unmanaged_objects(tmp_path: Path) -> None:
    config = Settings(
        tmp_path,
        "https://storage.example.invalid",
        "us-east-1",
        "bucket",
        "access",
        "secret",
        "mayfly-staging/",
        "path",
        7200,
        1000,
        25,
        "INFO",
    )
    storage = Storage(config)
    key = f"mayfly-staging/{uuid.uuid4()}"
    modified = datetime.now(UTC)
    with Stubber(storage.client) as stub:
        stub.add_response(
            "list_objects_v2",
            {
                "IsTruncated": False,
                "Name": "bucket",
                "Prefix": "mayfly-staging/",
                "MaxKeys": 1000,
                "Contents": [
                    {"Key": key, "LastModified": modified, "ETag": '"a"', "Size": 3, "StorageClass": "STANDARD"},
                    {
                        "Key": "mayfly-staging/unrelated",
                        "LastModified": modified,
                        "ETag": '"b"',
                        "Size": 3,
                        "StorageClass": "STANDARD",
                    },
                ],
            },
            {"Bucket": "bucket", "Prefix": "mayfly-staging/"},
        )
        assert list(storage.list_staged()) == [(key, modified)]


def test_presigned_url_keeps_provider_endpoint_path(tmp_path: Path) -> None:
    config = Settings(
        tmp_path,
        "https://storage.example.invalid/api/s3",
        "ca-central-1",
        "bucket",
        "access",
        "secret",
        "mayfly-staging/",
        "path",
        7200,
        1000,
        25,
        "INFO",
    )
    storage = Storage(config)
    key = f"mayfly-staging/{uuid.uuid4()}"
    parsed = urlparse(storage.sign_get(key, 7200))
    assert parsed.path == f"/api/s3/bucket/{key}"
