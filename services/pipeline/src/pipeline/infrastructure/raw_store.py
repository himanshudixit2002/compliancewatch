"""Where fetched files live: content-addressed, never overwritten (guide section 7)."""

import hashlib
from pathlib import Path
from typing import Protocol

from domain_kernel.documents import RawDocument

EXTENSIONS = {"application/pdf": "pdf", "text/html": "html", "application/json": "json"}


class RawDocumentStore(Protocol):
    def put(self, source_key: str, raw: RawDocument) -> str:
        """Store the bytes and return the URI; a second put of the same digest is a no-op."""
        ...

    def get(self, uri: str) -> bytes: ...


class LocalRawStore:
    """``<root>/<source>/<sha256>.<ext>``; the URI is ``file://`` plus that path."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, source_key: str, raw: RawDocument) -> str:
        extension = EXTENSIONS.get(raw.media_type.split(";")[0].strip(), "bin")
        path = self._root / source_key / f"{raw.sha256}.{extension}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw.content)
        return path.resolve().as_uri()

    def get(self, uri: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError(f"not a local uri: {uri}")
        return Path(uri.removeprefix("file://")).read_bytes()


class MemoryRawStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def put(self, source_key: str, raw: RawDocument) -> str:
        uri = f"memory://{source_key}/{raw.sha256}"
        self.files.setdefault(uri, raw.content)
        return uri

    def get(self, uri: str) -> bytes:
        return self.files[uri]


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
