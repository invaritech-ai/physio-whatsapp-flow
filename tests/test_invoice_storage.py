"""Tests for invoice storage backend helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import invoice_storage

pytestmark = pytest.mark.no_s3_mock


class _FakeS3Client:
    def __init__(self, presigned_url: str = "https://signed.example.com/invoice-3.pdf"):
        self.presigned_url = presigned_url
        self.put_object_calls: list[dict] = []
        self.generate_presigned_url_calls: list[tuple] = []

    def put_object(self, **kwargs):
        self.put_object_calls.append(kwargs)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def generate_presigned_url(self, *args, **kwargs):
        self.generate_presigned_url_calls.append((args, kwargs))
        return self.presigned_url


def test_upload_to_s3_sends_content_length_header(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice-3.pdf"
    payload = b"%PDF-1.4\nfake-pdf-content\n"
    pdf_path.write_bytes(payload)

    fake_s3 = _FakeS3Client()
    fake_config = lambda **kwargs: SimpleNamespace()
    fake_boto3 = SimpleNamespace(client=lambda _service, **_kwargs: fake_s3)
    fake_botocore = SimpleNamespace(config=SimpleNamespace(Config=fake_config))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore.config)

    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_bucket", "my-bucket")
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_endpoint_url", "https://example.compat.objectstorage.test")
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_prefix", "invoices")
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_public_base_url", None)
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_presign_ttl_seconds", 900)

    result = invoice_storage._upload_to_s3(
        invoice_id=3,
        client_name="Jane Doe",
        local_pdf_path=pdf_path,
        date_value=datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc),
    )

    # No public_base_url → stable s3:// reference (presigned URL comes via resolve_invoice_pdf_url)
    assert result == "s3://my-bucket/invoices/jane-doe_2026-05-06_AFIXEDSTRING_3.pdf"
    assert len(fake_s3.put_object_calls) == 1
    call = fake_s3.put_object_calls[0]
    assert call["Bucket"] == "my-bucket"
    assert call["Key"] == "invoices/jane-doe_2026-05-06_AFIXEDSTRING_3.pdf"
    assert call["ContentType"] == "application/pdf"
    assert call["ContentLength"] == len(payload)


def test_upload_to_s3_uses_public_base_url_when_configured(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice-12.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    fake_s3 = _FakeS3Client()
    fake_config = lambda **kwargs: SimpleNamespace()
    fake_boto3 = SimpleNamespace(client=lambda _service, **_kwargs: fake_s3)
    fake_botocore = SimpleNamespace(config=SimpleNamespace(Config=fake_config))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore.config)

    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_bucket", "my-bucket")
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_endpoint_url", "https://example.compat.objectstorage.test")
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_prefix", "invoices")
    monkeypatch.setattr(invoice_storage.settings, "invoice_s3_public_base_url", "https://cdn.example.com/public")

    result = invoice_storage._upload_to_s3(
        invoice_id=12,
        client_name=None,
        local_pdf_path=pdf_path,
        date_value=datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc),
    )

    assert (
        result
        == "https://cdn.example.com/public/invoices/client-12_2026-05-06_AFIXEDSTRING_12.pdf"
    )
    assert len(fake_s3.put_object_calls) == 1
    assert len(fake_s3.generate_presigned_url_calls) == 0
