"""The raw stores: content-addressed keys, never overwritten, read back only with the digest
their key names. The S3 store runs against the stubbed S3 endpoint."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.domain.errors import RawObjectCorruptError, RawObjectMissingError, RawStoreError
from pipeline.infrastructure.raw_store import (
    LocalRawStore,
    MemoryRawStore,
    S3RawStore,
    digest,
    digest_of,
    storage_key_for,
)
from pipeline.infrastructure.s3 import S3Client, S3Credentials
from pipeline.testing import StubS3

REF = DocumentRef(SourceId.new(), "https://example.test/doc")
PDF = RawDocument.from_bytes(REF, b"%PDF-1.4 hello", "application/pdf; charset=binary")
CREDENTIALS = S3Credentials("test-access-key", "test-secret-key")


def s3_store(stub: StubS3, **options: object) -> S3RawStore:
    client = S3Client(
        bucket=stub.bucket,
        region=stub.region,
        credentials=CREDENTIALS,
        endpoint_url="http://minio.test:9000",
        transport=stub.transport(),
        clock=lambda: datetime(2026, 10, 6, tzinfo=UTC),
        sleep=lambda _: None,
    )
    return S3RawStore(client, **options)  # type: ignore[arg-type]


def test_keys_name_the_digest() -> None:
    key = storage_key_for(PDF.sha256)
    assert key == f"{PDF.sha256[:2]}/{PDF.sha256}"
    assert digest_of(key) == digest_of(f"raw/{key}") == digest_of(f"a/b/{key}") == PDF.sha256
    assert digest(PDF.content) == PDF.sha256
    for bad in ("../etc/passwd", f"zz/{PDF.sha256}", PDF.sha256, f"raw/{PDF.sha256[:2]}"):
        with pytest.raises(ValueError, match="content-addressed"):
            digest_of(bad)
    with pytest.raises(ValueError, match="SHA-256"):
        storage_key_for("abc")


def test_the_local_store_is_content_addressed_and_never_overwrites(tmp_path: Path) -> None:
    store = LocalRawStore(tmp_path)
    key = store.put(PDF)
    assert key == storage_key_for(PDF.sha256)
    path = tmp_path / key
    assert path.read_bytes() == PDF.content
    assert store.uri(key) == path.resolve().as_uri()
    assert store.get(key) == PDF.content
    path.write_bytes(b"tampered")
    assert store.put(PDF) == key
    assert path.read_bytes() == b"tampered", "a stored file is never written again"
    with pytest.raises(RawObjectCorruptError, match="another digest"):
        store.get(key)
    assert [p.name for p in path.parent.iterdir()] == [PDF.sha256], "no partial file is left"


def test_the_local_store_reads_only_its_own_keys(tmp_path: Path) -> None:
    store = LocalRawStore(tmp_path)
    with pytest.raises(RawObjectMissingError):
        store.get(storage_key_for(hashlib.sha256(b"never stored").hexdigest()))
    for bad in ("../outside", f"raw/{storage_key_for(PDF.sha256)}"):
        with pytest.raises(ValueError, match="not a key of the local store"):
            store.get(bad)


def test_the_memory_store() -> None:
    store = MemoryRawStore()
    key = store.put(PDF)
    assert store.put(PDF) == key
    assert (store.files, store.puts) == ({key: PDF.content}, 2)
    assert store.uri(key) == f"memory://{key}"
    assert store.get(key) == PDF.content
    with pytest.raises(RawObjectMissingError):
        store.get(storage_key_for(hashlib.sha256(b"other").hexdigest()))


def test_the_s3_store_writes_once_encrypted_under_its_prefix() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    store = s3_store(stub, prefix="cw/raw/")
    key = store.put(PDF)
    assert key == f"cw/raw/{storage_key_for(PDF.sha256)}"
    content, headers = stub.objects[key]
    assert content == PDF.content
    assert headers["content-type"] == "application/pdf; charset=binary"
    assert headers["x-amz-server-side-encryption"] == "AES256"
    assert store.uri(key) == f"s3://cw-raw/{key}"
    assert store.put(PDF) == key, "a refetch finds the object and writes nothing"
    assert stub.methods() == ["HEAD", "PUT", "HEAD"]
    assert s3_store(stub, prefix="").get(key) == PDF.content, "keys stay readable"


def test_the_s3_store_uses_the_kms_key_or_no_encryption_at_all() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    s3_store(stub, encryption="aws:kms", kms_key_id="alias/cw-raw").put(PDF)
    (headers,) = (h for _, h in stub.objects.values())
    assert headers["x-amz-server-side-encryption"] == "aws:kms"
    assert headers["x-amz-server-side-encryption-aws-kms-key-id"] == "alias/cw-raw"
    plain = StubS3("cw-raw", CREDENTIALS)
    s3_store(plain, encryption="none").put(PDF)
    (headers,) = (h for _, h in plain.objects.values())
    assert not [name for name in headers if name.startswith("x-amz-server-side-encryption")]
    with pytest.raises(ValueError, match="needs encryption aws:kms"):
        s3_store(plain, kms_key_id="alias/cw-raw")
    with pytest.raises(ValueError, match="prefix must match"):
        s3_store(plain, prefix="/raw")


def test_the_s3_store_reports_what_it_could_not_do() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    store = s3_store(stub)
    with pytest.raises(RawObjectMissingError):
        store.get(f"raw/{storage_key_for(PDF.sha256)}")
    key = store.put(PDF)
    stub.objects[key] = (b"tampered", {})
    with pytest.raises(RawObjectCorruptError):
        store.get(key)
    stub.fail.extend([503, 503, 503])
    with pytest.raises(RawStoreError, match="503"):
        store.put(RawDocument.from_bytes(REF, b"another file", "application/pdf"))
    with pytest.raises(ValueError, match="content-addressed"):
        store.get("raw/not-a-digest")
