from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.services.invoice_documents import build_invoice_pdf_url


def _invoice_filename(invoice_id: int) -> str:
    return f"invoice-{invoice_id}.pdf"


def _storage_backend() -> str:
    backend = settings.invoice_storage_backend.strip().lower()
    if backend in {"local", "s3"}:
        return backend
    if backend == "auto":
        if settings.invoice_s3_bucket and settings.invoice_s3_endpoint_url:
            return "s3"
        return "local"
    return "local"


def _s3_object_key(invoice_id: int) -> str:
    prefix = settings.invoice_s3_prefix.strip("/")
    name = _invoice_filename(invoice_id)
    if not prefix:
        return name
    return f"{prefix}/{name}"


def _upload_to_s3(*, invoice_id: int, local_pdf_path: Path) -> str:
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError("boto3 is required for S3 invoice storage backend") from exc

    bucket = settings.invoice_s3_bucket
    endpoint_url = settings.invoice_s3_endpoint_url
    if not bucket or not endpoint_url:
        raise RuntimeError("invoice_s3_bucket and invoice_s3_endpoint_url are required for S3 backend")

    client_kwargs: dict[str, str] = {"endpoint_url": endpoint_url}
    if settings.invoice_s3_region:
        client_kwargs["region_name"] = settings.invoice_s3_region
    if settings.invoice_s3_access_key_id:
        client_kwargs["aws_access_key_id"] = settings.invoice_s3_access_key_id
    if settings.invoice_s3_secret_access_key:
        client_kwargs["aws_secret_access_key"] = settings.invoice_s3_secret_access_key

    s3 = boto3.client("s3", **client_kwargs)
    object_key = _s3_object_key(invoice_id)
    s3.upload_file(
        str(local_pdf_path),
        bucket,
        object_key,
        ExtraArgs={"ContentType": "application/pdf"},
    )

    if settings.invoice_s3_public_base_url:
        base = settings.invoice_s3_public_base_url.rstrip("/")
        return f"{base}/{object_key}"

    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=settings.invoice_s3_presign_ttl_seconds,
    )


def store_invoice_pdf(*, invoice_id: int, local_pdf_path: Path) -> str:
    backend = _storage_backend()
    if backend == "s3":
        return _upload_to_s3(invoice_id=invoice_id, local_pdf_path=local_pdf_path)
    return build_invoice_pdf_url(invoice_id)
