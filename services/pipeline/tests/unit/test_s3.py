"""The S3 client: Signature Version 4 against AWS's published examples, and the object calls
against a stubbed S3 endpoint that checks every signature the way S3 does."""

import hashlib
from datetime import UTC, datetime

import httpx2
import pytest

from pipeline.infrastructure.s3 import S3Client, S3Credentials, S3Error, object_path, sign
from pipeline.testing import StubS3

# The example credentials and requests of AWS's "Signature Calculations for the Authorization
# Header: Transferring Payload in a Single Chunk" (Amazon S3 API reference), public and
# deliberately invalid.
EXAMPLE = S3Credentials(
    "AKIAIOSFODNN7EXAMPLE",  # gitleaks:allow
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # gitleaks:allow
)
EXAMPLE_HOST = "examplebucket.s3.amazonaws.com"
EXAMPLE_DATE = datetime(2013, 5, 24, tzinfo=UTC)
EMPTY = hashlib.sha256(b"").hexdigest()
CREDENTIALS = S3Credentials("test-access-key", "test-secret-key")
NOW = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)


def signature(headers: dict[str, str]) -> str:
    return headers["authorization"].rsplit("Signature=", 1)[1]


@pytest.mark.parametrize(
    ("method", "path", "headers", "payload", "expected"),
    [
        (
            "GET",
            "/test.txt",
            {"range": "bytes=0-9"},
            b"",
            "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
        ),
        (
            "PUT",
            "/test%24file.text",
            {
                "date": "Fri, 24 May 2013 00:00:00 GMT",
                "x-amz-storage-class": "REDUCED_REDUNDANCY",
            },
            b"Welcome to Amazon S3.",
            "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd",
        ),
        (
            "GET",
            "/?lifecycle",
            {},
            b"",
            "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543",
        ),
        (
            "GET",
            "/?max-keys=2&prefix=J",
            {},
            b"",
            "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7",
        ),
    ],
    ids=["get-object", "put-object", "get-lifecycle", "list-objects"],
)
def test_signatures_match_the_aws_examples(
    method: str, path: str, headers: dict[str, str], payload: bytes, expected: str
) -> None:
    signed = sign(
        method,
        f"https://{EXAMPLE_HOST}{path}",
        {"host": EXAMPLE_HOST, **headers},
        hashlib.sha256(payload).hexdigest(),
        EXAMPLE,
        "us-east-1",
        EXAMPLE_DATE,
    )
    assert signature(signed) == expected
    assert signed["x-amz-date"] == "20130524T000000Z"
    assert signed["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
    )


def test_a_temporary_key_signs_its_session_token() -> None:
    temporary = S3Credentials("ASIAEXAMPLEKEY", "secret", session_token="token-of-the-session")
    signed = sign(
        "GET",
        f"https://{EXAMPLE_HOST}/k",
        {"host": EXAMPLE_HOST},
        EMPTY,
        temporary,
        "ap-south-1",
        NOW,
    )
    assert signed["x-amz-security-token"] == "token-of-the-session"
    assert "x-amz-security-token" in signed["authorization"]
    assert "token-of-the-session" not in repr(temporary)
    assert "secret" not in repr(temporary)


def test_keys_are_encoded_once_in_the_path() -> None:
    assert object_path("raw/ab/file name+$.pdf") == "raw/ab/file%20name%2B%24.pdf"


def client(stub: StubS3, **overrides: object) -> S3Client:
    values: dict[str, object] = {
        "bucket": stub.bucket,
        "region": stub.region,
        "credentials": CREDENTIALS,
        "endpoint_url": "http://minio.test:9000/",
        "transport": stub.transport(),
        "clock": lambda: NOW,
        "sleep": lambda _: None,
    }
    values.update(overrides)
    return S3Client(**values)  # type: ignore[arg-type]


def test_objects_go_in_and_come_out_path_style_on_an_endpoint() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    s3 = client(stub)
    assert s3.url("raw/ab/x") == "http://minio.test:9000/cw-raw/raw/ab/x"
    assert s3.head("raw/ab/x") is False
    assert s3.put("raw/ab/x", b"%PDF-1.7", content_type="application/pdf") is True
    assert s3.head("raw/ab/x") is True
    assert s3.get("raw/ab/x") == b"%PDF-1.7"
    assert stub.methods() == ["HEAD", "PUT", "HEAD", "GET"]
    put = stub.requests[1]
    assert put.headers["host"] == "minio.test:9000"
    assert put.headers["if-none-match"] == "*"
    assert "if-none-match" in put.headers["authorization"]


def test_on_aws_the_bucket_is_in_the_host() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    s3 = client(stub, endpoint_url=None)
    assert s3.url("raw/ab/x") == "https://cw-raw.s3.ap-south-1.amazonaws.com/raw/ab/x"
    assert s3.put("raw/ab/x", b"bytes", content_type="text/plain")
    assert stub.objects["raw/ab/x"][0] == b"bytes"
    assert stub.requests[0].headers["host"] == "cw-raw.s3.ap-south-1.amazonaws.com"


def test_a_conditional_put_of_an_existing_key_writes_nothing() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    s3 = client(stub)
    assert s3.put("k/ab/x", b"first", content_type="text/plain")
    assert s3.put("k/ab/x", b"second", content_type="text/plain") is False
    assert stub.objects["k/ab/x"][0] == b"first"


def test_a_failing_call_is_tried_again_and_then_reported() -> None:
    stub = StubS3("cw-raw", CREDENTIALS, fail=[503, 500])
    slept: list[float] = []
    assert client(stub, sleep=slept.append).head("k") is False
    assert slept == [0.2, 0.4]
    assert len(stub.requests) == 3
    stub.fail.extend([503, 503, 503])
    with pytest.raises(S3Error, match="503 InternalError") as failed:
        client(stub).get("k")
    assert failed.value.status == 503


def test_a_transport_failure_after_every_try_is_an_s3_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    s3 = S3Client(
        bucket="cw-raw",
        region="ap-south-1",
        credentials=CREDENTIALS,
        endpoint_url="http://minio.test:9000",
        transport=httpx2.MockTransport(refuse),
        sleep=lambda _: None,
    )
    with pytest.raises(S3Error, match="no answer ConnectError") as failed:
        s3.put("k", b"x", content_type="text/plain")
    assert failed.value.status is None


def test_refusals_carry_the_status_and_the_code() -> None:
    stub = StubS3("cw-raw", CREDENTIALS)
    with pytest.raises(S3Error, match="404 NoSuchKey") as missing:
        client(stub).get("raw/ab/missing")
    assert (missing.value.status, missing.value.code) == (404, "NoSuchKey")
    wrong = S3Credentials("test-access-key", "another-secret")
    with pytest.raises(S3Error, match="403 SignatureDoesNotMatch"):
        client(stub, credentials=wrong).put("k", b"x", content_type="text/plain")
    assert client(stub, credentials=wrong).head("k") is False, "403 on HEAD reads as not found"
    with pytest.raises(S3Error, match="404 NoSuchBucket"):
        client(stub, bucket="other-bucket").get("k")


@pytest.mark.parametrize("bucket", ["Upper", "a", "dotted.bucket", "-leading"])
def test_a_bucket_name_s3_would_refuse_is_refused(bucket: str) -> None:
    with pytest.raises(ValueError, match="bucket must match"):
        S3Client(bucket=bucket, region="ap-south-1", credentials=CREDENTIALS)
