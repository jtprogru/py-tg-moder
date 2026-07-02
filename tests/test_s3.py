import hashlib

import httpx
import pytest

from core.s3 import S3Client, S3Error, _signature

# -- SigV4 signing ---------------------------------------------------------------


def test_signature_matches_aws_reference_vector():
    """The official example from the AWS SigV4 docs: known inputs -> published
    signature. Passing this proves canonicalization and key derivation are
    correct without talking to a real S3."""
    signed, signature = _signature(
        method="GET",
        path="/",
        query={"Action": "ListUsers", "Version": "2010-05-08"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Host": "iam.amazonaws.com",
            "X-Amz-Date": "20150830T123600Z",
        },
        payload_hash=hashlib.sha256(b"").hexdigest(),
        region="us-east-1",
        service="iam",
        secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        amz_date="20150830T123600Z",
    )
    assert signed == "content-type;host;x-amz-date"
    assert signature == "5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"


# -- client operations over a mock transport ---------------------------------------


def _client(handler) -> S3Client:
    return S3Client(
        endpoint="https://s3.example.com",
        region="us-east-1",
        bucket="bkt",
        access_key="AK",
        secret_key="SK",
        transport=httpx.MockTransport(handler),
    )


def test_put_object_sends_signed_request():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["sha"] = request.headers["x-amz-content-sha256"]
        seen["body"] = request.content
        return httpx.Response(200)

    _client(handler).put_object("pfx/moder-1.sqlite", b"data")
    assert seen["method"] == "PUT"
    assert seen["url"] == "https://s3.example.com/bkt/pfx/moder-1.sqlite"
    assert seen["body"] == b"data"
    assert seen["sha"] == hashlib.sha256(b"data").hexdigest()
    assert seen["auth"].startswith("AWS4-HMAC-SHA256 Credential=AK/")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in seen["auth"]


def test_list_keys_follows_pagination():
    pages = [
        '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<IsTruncated>true</IsTruncated><NextContinuationToken>tok+1</NextContinuationToken>"
        "<Contents><Key>p/a.sqlite</Key></Contents><Contents><Key>p/b.sqlite</Key></Contents>"
        "</ListBucketResult>",
        '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<IsTruncated>false</IsTruncated><Contents><Key>p/c.sqlite</Key></Contents></ListBucketResult>",
    ]
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, text=pages[len(urls) - 1])

    assert _client(handler).list_keys("p/") == ["p/a.sqlite", "p/b.sqlite", "p/c.sqlite"]
    assert len(urls) == 2
    assert "continuation-token=tok%2B1" in urls[1]


def test_list_keys_without_namespace():
    # Some S3-compatible providers omit the xmlns declaration.
    def handler(request):
        return httpx.Response(200, text="<ListBucketResult><Contents><Key>p/a.sqlite</Key></Contents></ListBucketResult>")

    assert _client(handler).list_keys("p/") == ["p/a.sqlite"]


def test_delete_object_accepts_204():
    def handler(request):
        assert request.method == "DELETE"
        return httpx.Response(204)

    _client(handler).delete_object("p/a.sqlite")


def test_error_status_raises():
    def handler(request):
        return httpx.Response(403, text="<Error>AccessDenied</Error>")

    with pytest.raises(S3Error, match="403"):
        _client(handler).put_object("k", b"")


def test_bad_endpoint_is_rejected_early():
    with pytest.raises(S3Error, match="endpoint"):
        S3Client(endpoint="s3.example.com", region="r", bucket="b", access_key="a", secret_key="s")
