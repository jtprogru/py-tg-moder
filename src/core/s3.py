# -*- coding: utf-8 -*-
"""Minimal S3-compatible client (AWS Signature V4) for backup mirroring.

Only the three operations the backup job needs: PUT object, LIST objects by
prefix, DELETE object. Hand-rolled on top of httpx (already here as a PTB
dependency) so the image stays free of boto3; path-style addressing works
with AWS, MinIO and other S3-compatible providers alike.
"""

import hashlib
import hmac
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import httpx


class S3Error(RuntimeError):
    """The storage rejected a request (bad credentials, missing bucket, ...)."""


def _quote(value: str, safe: str = "-_.~") -> str:
    return urllib.parse.quote(value, safe=safe)


def _canonical_query(query: dict) -> str:
    return "&".join(f"{_quote(k)}={_quote(str(v))}" for k, v in sorted(query.items()))


def _signature(
    *, method: str, path: str, query: dict, headers: dict, payload_hash: str, region: str, service: str, secret_key: str, amz_date: str
) -> tuple[str, str]:
    """AWS SigV4 over the canonical request; returns (signed_headers, signature).

    ``headers`` must already contain everything to be signed (host, x-amz-date,
    and for S3 also x-amz-content-sha256). Kept generic and side-effect-free so
    it can be verified against the official AWS test vector.
    """
    lower = {name.lower(): str(value).strip() for name, value in headers.items()}
    signed = ";".join(sorted(lower))
    canonical_request = "\n".join(
        [
            method,
            path,
            _canonical_query(query),
            "".join(f"{name}:{lower[name]}\n" for name in sorted(lower)),
            signed,
            payload_hash,
        ]
    )
    date = amz_date[:8]
    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
    key = b"AWS4" + secret_key.encode()
    for part in (date, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return signed, hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()


class S3Client:
    """PUT/LIST/DELETE against a single bucket, path-style addressing."""

    def __init__(self, *, endpoint: str, region: str, bucket: str, access_key: str, secret_key: str, transport: Optional[httpx.BaseTransport] = None):
        parsed = urllib.parse.urlparse(endpoint.rstrip("/"))
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise S3Error(f"Некорректный S3 endpoint: {endpoint!r} (нужен полный URL, например https://s3.example.com)")
        self._base = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        self._region = region
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        # Tests inject an httpx.MockTransport here.
        self._transport = transport

    def _request(self, method: str, key: str = "", query: Optional[dict] = None, body: bytes = b"", expect: tuple = (200,)) -> httpx.Response:
        query = query or {}
        # Canonical URI: each segment percent-encoded, slashes preserved.
        path = f"/{_quote(self._bucket)}"
        if key:
            path += "/" + _quote(key, safe="/-_.~")
        payload_hash = hashlib.sha256(body).hexdigest()
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        headers = {"host": self._host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        signed, signature = _signature(
            method=method,
            path=path,
            query=query,
            headers=headers,
            payload_hash=payload_hash,
            region=self._region,
            service="s3",
            secret_key=self._secret_key,
            amz_date=amz_date,
        )
        scope = f"{amz_date[:8]}/{self._region}/s3/aws4_request"
        headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope}, SignedHeaders={signed}, Signature={signature}"
        # The URL must carry the exact query string that was signed.
        url = self._base + path + (f"?{_canonical_query(query)}" if query else "")
        with httpx.Client(timeout=120, transport=self._transport) as client:
            response = client.request(method, url, headers=headers, content=body)
        if response.status_code not in expect:
            raise S3Error(f"S3 {method} {path} -> {response.status_code}: {response.text[:200]}")
        return response

    def put_object(self, key: str, body: bytes) -> None:
        self._request("PUT", key, body=body)

    def list_keys(self, prefix: str) -> list[str]:
        """All object keys under ``prefix`` (follows ListObjectsV2 pagination)."""
        keys: list[str] = []
        token: Optional[str] = None
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            root = ET.fromstring(self._request("GET", query=query).text)
            keys += [el.text for el in root.findall("{*}Contents/{*}Key") if el.text]
            token = root.findtext("{*}NextContinuationToken")
            if (root.findtext("{*}IsTruncated") or "").lower() != "true" or not token:
                return keys

    def delete_object(self, key: str) -> None:
        self._request("DELETE", key, expect=(200, 204))
