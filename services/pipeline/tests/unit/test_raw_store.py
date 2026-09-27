from pathlib import Path

import pytest

from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.infrastructure.raw_store import LocalRawStore, MemoryRawStore, digest

REF = DocumentRef(SourceId.new(), "https://example.test/doc")


def test_local_store_is_content_addressed_and_never_overwrites(tmp_path: Path) -> None:
    store = LocalRawStore(tmp_path)
    raw = RawDocument.from_bytes(REF, b"%PDF-1.4 hello", "application/pdf; charset=binary")
    uri = store.put("cbic", raw)
    assert uri.endswith(f"/cbic/{raw.sha256}.pdf")
    path = Path(uri.removeprefix("file://"))
    path.write_bytes(b"tampered")
    assert store.put("cbic", raw) == uri
    assert store.get(uri) == b"tampered"
    assert digest(raw.content) == raw.sha256
    with pytest.raises(ValueError, match="not a local uri"):
        store.get("s3://bucket/key")


def test_unknown_media_types_get_the_bin_extension(tmp_path: Path) -> None:
    raw = RawDocument.from_bytes(REF, b"x", "application/x-unknown")
    assert LocalRawStore(tmp_path).put("s", raw).endswith(".bin")


def test_memory_store() -> None:
    store = MemoryRawStore()
    raw = RawDocument.from_bytes(REF, b"abc", "text/html")
    uri = store.put("gstn", raw)
    assert uri == f"memory://gstn/{raw.sha256}"
    assert store.get(uri) == b"abc"
