"""Private S3-compatible object operations limited to managed UUID keys."""

import re
from collections.abc import Iterator
from datetime import datetime
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .errors import PublishError
from .settings import Settings

MANAGED_NAME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.bucket
        self.prefix = settings.prefix
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            region_name=settings.region,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            config=Config(
                signature_version="s3v4",
                retries={"mode": "standard", "max_attempts": 3},
                connect_timeout=10,
                read_timeout=45,
                s3={"addressing_style": settings.addressing_style},
            ),
        )

    def _check_key(self, key: str) -> None:
        if not key.startswith(self.prefix) or not MANAGED_NAME.fullmatch(key[len(self.prefix) :]):
            raise PublishError("invalid_object", "Object is outside the staging prefix")

    def upload(self, key: str, stream: BinaryIO, mime_type: str) -> None:
        self._check_key(key)
        try:
            stream.seek(0)
            self.client.put_object(Bucket=self.bucket, Key=key, Body=stream, ContentType=mime_type)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise PublishError("storage_unavailable", "Remote upload failed") from exc

    def head(self, key: str) -> dict[str, object] | None:
        self._check_key(key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
            return {"ContentLength": response["ContentLength"], "ContentType": response.get("ContentType")}
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise PublishError("storage_unavailable", "Remote object check failed") from exc
        except BotoCoreError as exc:
            raise PublishError("storage_unavailable", "Remote object check failed") from exc

    def delete(self, key: str) -> None:
        self._check_key(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise PublishError("storage_unavailable", "Remote deletion failed") from exc

    def sign_get(self, key: str, ttl: int) -> str:
        self._check_key(key)
        try:
            return str(
                self.client.generate_presigned_url(
                    "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl, HttpMethod="GET"
                )
            )
        except (BotoCoreError, ClientError) as exc:
            raise PublishError("storage_unavailable", "Could not create signed URL") from exc

    def list_staged(self) -> Iterator[tuple[str, datetime]]:
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if key.startswith(self.prefix) and MANAGED_NAME.fullmatch(key[len(self.prefix) :]):
                        yield key, item["LastModified"]
        except (BotoCoreError, ClientError) as exc:
            raise PublishError("storage_unavailable", "Remote staging inventory failed") from exc
