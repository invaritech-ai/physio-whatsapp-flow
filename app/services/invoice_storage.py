from __future__ import annotations

from pathlib import Path
from datetime import datetime
from app.core.config import settings

from app.services.naming import invoice_filename as _invoice_filename


def _s3_object_key(
    *,
    invoice_id: int,
    client_name: str | None,
    date_value: datetime | None = None,
) -> str:
    prefix = settings.invoice_s3_prefix.strip("/")
    name = _invoice_filename(
        invoice_id=invoice_id,
        client_name=client_name,
        date_value=date_value,
    )
    if not prefix:
        return name
    return f"{prefix}/{name}"


def _upload_to_s3(
    *,
    invoice_id: int,
    client_name: str | None,
    local_pdf_path: Path,
    date_value: datetime | None = None,
) -> str:
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError("boto3 is required for S3 invoice storage") from exc

    bucket = settings.invoice_s3_bucket
    endpoint_url = settings.invoice_s3_endpoint_url
    if not bucket or not endpoint_url:
        raise RuntimeError("invoice_s3_bucket and invoice_s3_endpoint_url are required")

    client_kwargs: dict[str, str] = {"endpoint_url": endpoint_url}
    if settings.invoice_s3_region:
        client_kwargs["region_name"] = settings.invoice_s3_region
    if settings.invoice_s3_access_key_id:
        client_kwargs["aws_access_key_id"] = settings.invoice_s3_access_key_id
    if settings.invoice_s3_secret_access_key:
        client_kwargs["aws_secret_access_key"] = settings.invoice_s3_secret_access_key

    from botocore.config import Config

    # OCI requires SigV4 (default) — do NOT set signature_version="s3" (SigV2).
    # boto3 >= 1.36 changed request_checksum_calculation default to "when_supported",
    # which sends Transfer-Encoding: chunked + x-amz-sdk-checksum-algorithm on every
    # PutObject. OCI rejects chunked uploads with MissingContentLength.
    # "when_required" disables that for PutObject (no checksum required by the operation).
    # addressing_style="path" is required because the OCI endpoint is namespace-scoped.
    s3 = boto3.client(
        "s3",
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            s3={"addressing_style": "path"},
        ),
        **client_kwargs,
    )
    object_key = _s3_object_key(
        invoice_id=invoice_id,
        client_name=client_name,
        date_value=date_value,
    )
    pdf_bytes = local_pdf_path.read_bytes()
    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=pdf_bytes,
        ContentLength=len(pdf_bytes),
        ContentType="application/pdf",
    )

    if settings.invoice_s3_public_base_url:
        base = settings.invoice_s3_public_base_url.rstrip("/")
        return f"{base}/{object_key}"

    # Store a stable reference rather than a pre-signed URL that expires.
    # The actual download URL is generated fresh on each API request via resolve_invoice_pdf_url.
    return f"s3://{bucket}/{object_key}"


def store_invoice_pdf(
    *,
    invoice_id: int,
    client_name: str | None,
    local_pdf_path: Path,
    date_value: datetime | None = None,
) -> str:
    return _upload_to_s3(
        invoice_id=invoice_id,
        client_name=client_name,
        local_pdf_path=local_pdf_path,
        date_value=date_value,
    )


def resolve_invoice_pdf_url(stored_url: str | None) -> str | None:
    """Convert a stored stable s3:// reference to a fresh pre-signed (or public) URL.

    - ``None`` / empty → returned as-is
    - Already a public/http URL → returned as-is
    - ``s3://bucket/key`` → fresh pre-signed URL (or public URL if base_url configured)
    """
    if not stored_url or not stored_url.startswith("s3://"):
        return stored_url

    without_scheme = stored_url[len("s3://") :]
    bucket, _, object_key = without_scheme.partition("/")
    if not bucket or not object_key:
        return stored_url

    if settings.invoice_s3_public_base_url:
        base = settings.invoice_s3_public_base_url.rstrip("/")
        return f"{base}/{object_key}"

    endpoint_url = settings.invoice_s3_endpoint_url
    if not endpoint_url:
        return stored_url

    try:
        import boto3
    except ModuleNotFoundError:
        return stored_url

    client_kwargs: dict[str, str] = {"endpoint_url": endpoint_url}
    if settings.invoice_s3_region:
        client_kwargs["region_name"] = settings.invoice_s3_region
    if settings.invoice_s3_access_key_id:
        client_kwargs["aws_access_key_id"] = settings.invoice_s3_access_key_id
    if settings.invoice_s3_secret_access_key:
        client_kwargs["aws_secret_access_key"] = settings.invoice_s3_secret_access_key

    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            s3={"addressing_style": "path"},
        ),
        **client_kwargs,
    )
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=settings.invoice_s3_presign_ttl_seconds,
    )
