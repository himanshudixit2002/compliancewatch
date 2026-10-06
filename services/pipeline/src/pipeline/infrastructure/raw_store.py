"""Where fetched files live: by their content, never overwritten (guide section 7).

A file's storage key names the SHA-256 of its bytes, ``<first two hex digits>/<sha256>``, with
the S3 store's prefix in front (``raw/ab/ab12...``), so the same bytes always land under the same
key and a refetch never stores a second copy. Each store checks what it reads against the digest
its key names. Three stores implement the domain's ``RawStore``, picked by
``CW_PIPELINE_RAW_STORE`` (``pipeline.stores``):

- ``S3RawStore``: a bucket, with server-side encryption (SSE-S3 or SSE-KMS) on every write; a
  write first asks whether the key exists and is conditional (``If-None-Match: *``), so neither a
  refetch nor two writers at once make a second version in a versioned bucket;
- ``LocalRawStore``: a directory, written through a temporary file and an atomic rename;
- ``MemoryRawStore``: a dict, for tests.
"""

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Final, Literal

from domain_kernel.documents import RawDocument
from pipeline.domain.errors import RawObjectCorruptError, RawObjectMissingError, RawStoreError
from pipeline.infrastructure.s3 import S3Client, S3Error

Encryption = Literal["AES256", "aws:kms", "none"]
"""Server-side encryption of what the S3 store writes: SSE-S3, SSE-KMS, or none (a local MinIO
without a key service; refused in staging and production)."""

CONTENT_KEY_PATTERN: Final = r"[0-9a-f]{2}/[0-9a-f]{64}"
PREFIX_PATTERN: Final = r"^([A-Za-z0-9!_.*'()-]+/)*$"
"""An S3 key prefix: empty, or segments of S3's safe characters, each ending with ``/``."""

_CONTENT_KEY = re.compile(CONTENT_KEY_PATTERN)
_KEY = re.compile(rf"(?P<prefix>(?:[A-Za-z0-9!_.*'()-]+/)*)(?P<content>{CONTENT_KEY_PATTERN})")
_PREFIX = re.compile(PREFIX_PATTERN)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def storage_key_for(sha256: str) -> str:
    """The content part of every storage key: ``<first two hex digits>/<sha256>``."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError(f"not a SHA-256 hex digest: {sha256!r}")
    return f"{sha256[:2]}/{sha256}"


def digest_of(storage_key: str) -> str:
    """The SHA-256 a storage key names; ``ValueError`` for a key no store here would write."""
    found = _KEY.fullmatch(storage_key)
    if found is None:
        raise ValueError(f"not a content-addressed storage key: {storage_key!r}")
    fan, sha256 = found.group("content").split("/")
    if sha256[:2] != fan:
        raise ValueError(f"not a content-addressed storage key: {storage_key!r}")
    return sha256


def checked(storage_key: str, content: bytes) -> bytes:
    """``content`` when its digest is the one ``storage_key`` names."""
    if digest(content) != digest_of(storage_key):
        raise RawObjectCorruptError(f"the bytes under {storage_key} have another digest")
    return content


class LocalRawStore:
    """``<root>/<ab>/<sha256>``; the URI is ``file://`` plus that path."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, raw: RawDocument) -> str:
        key = storage_key_for(raw.sha256)
        path = self._root / key
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
            partial.write_bytes(raw.content)
            os.replace(partial, path)
        return key

    def get(self, storage_key: str) -> bytes:
        try:
            content = self._path(storage_key).read_bytes()
        except FileNotFoundError as exc:
            raise RawObjectMissingError(f"no file under {storage_key}") from exc
        return checked(storage_key, content)

    def uri(self, storage_key: str) -> str:
        return self._path(storage_key).resolve().as_uri()

    def _path(self, storage_key: str) -> Path:
        if not _CONTENT_KEY.fullmatch(storage_key):
            raise ValueError(f"not a key of the local store: {storage_key!r}")
        return self._root / storage_key


class MemoryRawStore:
    """``files`` by storage key; the URI is ``memory://<key>``."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.puts = 0

    def put(self, raw: RawDocument) -> str:
        self.puts += 1
        key = storage_key_for(raw.sha256)
        self.files.setdefault(key, raw.content)
        return key

    def get(self, storage_key: str) -> bytes:
        content = self.files.get(storage_key)
        if content is None:
            raise RawObjectMissingError(f"no file under {storage_key}")
        return checked(storage_key, content)

    def uri(self, storage_key: str) -> str:
        return f"memory://{storage_key}"


class S3RawStore:
    """``<prefix><ab>/<sha256>`` in the client's bucket, written with server-side encryption;
    the URI is ``s3://<bucket>/<key>``. A key written under another prefix stays readable."""

    def __init__(
        self,
        client: S3Client,
        *,
        prefix: str = "raw/",
        encryption: Encryption = "AES256",
        kms_key_id: str | None = None,
    ) -> None:
        if not _PREFIX.fullmatch(prefix):
            raise ValueError(f"prefix must match {PREFIX_PATTERN}, got {prefix!r}")
        if kms_key_id and encryption != "aws:kms":
            raise ValueError("a KMS key id needs encryption aws:kms")
        self._client = client
        self._prefix = prefix
        self._headers: dict[str, str] = {}
        if encryption != "none":
            self._headers["x-amz-server-side-encryption"] = encryption
        if kms_key_id:
            self._headers["x-amz-server-side-encryption-aws-kms-key-id"] = kms_key_id

    def put(self, raw: RawDocument) -> str:
        key = self._prefix + storage_key_for(raw.sha256)
        try:
            if not self._client.head(key):
                self._client.put(
                    key, raw.content, content_type=raw.media_type, headers=self._headers
                )
        except S3Error as exc:
            raise RawStoreError(str(exc)) from exc
        return key

    def get(self, storage_key: str) -> bytes:
        digest_of(storage_key)
        try:
            content = self._client.get(storage_key)
        except S3Error as exc:
            if exc.status == 404:
                raise RawObjectMissingError(f"no object under {storage_key}") from exc
            raise RawStoreError(str(exc)) from exc
        return checked(storage_key, content)

    def uri(self, storage_key: str) -> str:
        return f"s3://{self._client.bucket}/{storage_key}"
