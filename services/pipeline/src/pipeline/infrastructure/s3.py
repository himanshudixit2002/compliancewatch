"""A small S3 client: the three object calls the raw store needs (HEAD, PUT and GET), signed
with AWS Signature Version 4 over httpx2.

No AWS SDK is a dependency of the workspace and the raw store needs nothing more, so this is the
whole client:

- path-style URLs on an endpoint (``endpoint_url``: MinIO in dev, any S3-compatible store), and
  virtual-hosted ones on AWS (``https://<bucket>.s3.<region>.amazonaws.com/<key>``);
- a static access key, with its session token when the key is temporary;
- the payload's SHA-256 in ``x-amz-content-sha256``, which S3 checks the body against;
- a few tries, with backoff, of a call that a 500, 502, 503 or 504 or a transport error failed.

``sign`` is the signature itself; its tests replay AWS's published examples.
"""

import hashlib
import hmac
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote, unquote, urlsplit

import httpx2

ALGORITHM: Final = "AWS4-HMAC-SHA256"
SERVICE: Final = "s3"
UNRESERVED: Final = "-_.~"
RETRY_STATUSES: Final = frozenset({500, 502, 503, 504})
BUCKET_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$"
"""A bucket name with no dots, so a virtual-hosted URL keeps its TLS certificate valid."""

_BUCKET = re.compile(BUCKET_PATTERN)
_ERROR_CODE = re.compile(rb"<Code>([^<]{1,100})</Code>")


@dataclass(frozen=True, slots=True)
class S3Credentials:
    access_key_id: str
    secret_access_key: str = field(repr=False)
    session_token: str | None = field(default=None, repr=False)


class S3Error(RuntimeError):
    """A call S3 refused or that failed after its tries. ``status`` is None when no answer came;
    ``code`` is S3's error code (``NoSuchKey``, ``AccessDenied``) when it sent one."""

    def __init__(self, method: str, key: str, status: int | None, code: str) -> None:
        self.method = method
        self.key = key
        self.status = status
        self.code = code
        answered = "no answer" if status is None else f"{status}"
        super().__init__(f"S3 {method} {key}: {answered} {code}".rstrip())


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_access_key: str, day: str, region: str) -> bytes:
    """The key of one day, region and service, derived from the secret."""
    key = _hmac(f"AWS4{secret_access_key}".encode(), day)
    key = _hmac(key, region)
    key = _hmac(key, SERVICE)
    return _hmac(key, "aws4_request")


def canonical_query(query: str) -> str:
    """The query string's parameters URI-encoded and sorted, each as ``name=value``."""
    pairs = []
    for item in query.split("&"):
        if not item:
            continue
        name, _, value = item.partition("=")
        pairs.append(
            (quote(unquote(name), safe=UNRESERVED), quote(unquote(value), safe=UNRESERVED))
        )
    return "&".join(f"{name}={value}" for name, value in sorted(pairs))


def sign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload_sha256: str,
    credentials: S3Credentials,
    region: str,
    now: datetime,
) -> dict[str, str]:
    """``headers`` with ``x-amz-date``, ``x-amz-content-sha256``, the session token when there is
    one, and the ``authorization`` that signs them all. Every header given is signed, so pass the
    ones the request sends as it sends them, ``host`` among them. The URL's path is used as it
    is: encode a key with ``object_path`` first, as S3 encodes it once."""
    amz_date = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    signed = {name.lower(): " ".join(str(value).split()) for name, value in headers.items()}
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_sha256
    if credentials.session_token:
        signed["x-amz-security-token"] = credentials.session_token
    names = sorted(signed)
    parts = urlsplit(url)
    canonical_request = "\n".join(
        [
            method.upper(),
            parts.path or "/",
            canonical_query(parts.query),
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            payload_sha256,
        ]
    )
    scope = f"{day}/{region}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    signature = hmac.new(
        signing_key(credentials.secret_access_key, day, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signed["authorization"] = (
        f"{ALGORITHM} Credential={credentials.access_key_id}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return signed


def object_path(key: str) -> str:
    """A key as it goes in a URL path: every byte but the unreserved ones and ``/`` encoded."""
    return quote(key, safe="/" + UNRESERVED)


class S3Client:
    """HEAD, PUT and GET of the objects of one bucket."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        credentials: S3Credentials,
        endpoint_url: str | None = None,
        transport: httpx2.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
        tries: int = 3,
        backoff_seconds: float = 0.2,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not _BUCKET.fullmatch(bucket):
            raise ValueError(f"bucket must match {BUCKET_PATTERN}, got {bucket!r}")
        if tries < 1:
            raise ValueError("tries must be at least 1")
        self._bucket = bucket
        self._region = region
        self._credentials = credentials
        self._endpoint = None if endpoint_url is None else endpoint_url.rstrip("/")
        self._client = httpx2.Client(
            timeout=timeout_seconds, transport=transport, follow_redirects=False
        )
        self._tries = tries
        self._backoff = backoff_seconds
        self._clock = clock
        self._sleep = sleep

    @property
    def bucket(self) -> str:
        return self._bucket

    def close(self) -> None:
        self._client.close()

    def url(self, key: str) -> str:
        """Path-style on an endpoint, virtual-hosted on AWS."""
        if self._endpoint is not None:
            return f"{self._endpoint}/{self._bucket}/{object_path(key)}"
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{object_path(key)}"

    def head(self, key: str) -> bool:
        """Whether the object exists. A 403 counts as not found, which is what S3 answers for a
        missing key to a role that may not list the bucket; a PUT then settles it."""
        response = self._send("HEAD", key)
        if response.status_code == 200:
            return True
        if response.status_code in (403, 404):
            return False
        raise _error("HEAD", key, response)

    def put(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        headers: Mapping[str, str] | None = None,
    ) -> bool:
        """Write the object unless it exists (``If-None-Match: *``); True when this call wrote
        it, False when S3 answered that it was there (412)."""
        sent = {"content-type": content_type, "if-none-match": "*", **(headers or {})}
        response = self._send("PUT", key, body=body, headers=sent)
        if response.status_code == 200:
            return True
        if response.status_code == 412:
            return False
        raise _error("PUT", key, response)

    def get(self, key: str) -> bytes:
        """The object's bytes; ``S3Error`` with status 404 when there is none."""
        response = self._send("GET", key)
        if response.status_code == 200:
            return response.content
        raise _error("GET", key, response)

    def _send(
        self,
        method: str,
        key: str,
        *,
        body: bytes = b"",
        headers: Mapping[str, str] | None = None,
    ) -> httpx2.Response:
        url = self.url(key)
        payload = hashlib.sha256(body).hexdigest()
        failure = S3Error(method, key, None, "not sent")
        for attempt in range(1, self._tries + 1):
            signed = sign(
                method,
                url,
                {"host": urlsplit(url).netloc, **(headers or {})},
                payload,
                self._credentials,
                self._region,
                self._clock(),
            )
            try:
                response = self._client.request(method, url, headers=signed, content=body or None)
            except httpx2.TransportError as exc:
                failure = S3Error(method, key, None, f"{type(exc).__name__}: {exc}")
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                failure = _error(method, key, response)
            if attempt < self._tries:
                self._sleep(self._backoff * 2 ** (attempt - 1))
        raise failure


def _error(method: str, key: str, response: httpx2.Response) -> S3Error:
    found = _ERROR_CODE.search(response.content or b"")
    code = found.group(1).decode("utf-8", errors="replace") if found else ""
    return S3Error(method, key, response.status_code, code)
