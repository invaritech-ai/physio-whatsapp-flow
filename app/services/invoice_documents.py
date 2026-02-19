from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _to_ascii(value: str | None) -> str:
    if not value:
        return "-"
    normalized = value.replace("\r\n", ", ").replace("\n", ", ")
    return normalized.encode("latin-1", "replace").decode("latin-1")


def _invoice_filename(invoice_id: int) -> str:
    return f"invoice-{invoice_id}.pdf"


def _invoice_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.invoice_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _format_invoice_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    localized = value.astimezone(_invoice_timezone())
    hour_12 = localized.strftime("%I").lstrip("0") or "0"
    minute = localized.strftime("%M")
    suffix = localized.strftime("%p").lower()
    return f"{localized.strftime('%B')} {localized.day}, {localized.year} - {hour_12}:{minute}{suffix}"


def _invoice_storage_dir() -> Path:
    root = Path(settings.invoice_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def invoice_pdf_path(invoice_id: int) -> Path:
    return _invoice_storage_dir() / _invoice_filename(invoice_id)


def build_invoice_pdf_url(invoice_id: int) -> str:
    public_path = "/" + settings.invoice_public_path.strip("/")
    relative_url = f"{public_path}/{_invoice_filename(invoice_id)}"
    if not settings.invoice_public_base_url:
        return relative_url
    return f"{settings.invoice_public_base_url.rstrip('/')}{relative_url}"


def build_invoice_pdf_bytes(
    *,
    invoice_id: int,
    client_name: str | None,
    client_address: str | None,
    client_phone: str,
    amount_cents: int,
    currency: str,
    description: str,
    diagnosis: str | None = None,
    session_start_at: datetime | None = None,
    therapist_name: str | None = None,
    therapist_license_number: str | None = None,
    payment_mode: str | None = None,
    special_notes: str | None = None,
    issued_at: datetime | None = None,
) -> bytes:
    issued = issued_at or datetime.now(timezone.utc)
    amount_display = f"{amount_cents / 100:.2f}"
    session_display = _format_invoice_datetime(session_start_at)
    issued_display = _format_invoice_datetime(issued)
    payer_name = _to_ascii(client_name) if client_name else "Client"
    client_address_line = _to_ascii(client_address) if client_address else ""
    therapist_line = _to_ascii(therapist_name) if therapist_name else ""
    therapist_license_line = _to_ascii(therapist_license_number) if therapist_license_number else "-"
    provider_line = f"{therapist_line}, License #{therapist_license_line}" if therapist_line else f"License #{therapist_license_line}"
    diagnosis_line = _to_ascii(diagnosis) if diagnosis else "-"
    payment_mode_line = _to_ascii(payment_mode) if payment_mode else "N/A"
    special_notes_line = _to_ascii(special_notes) if special_notes else "-"
    lines = [
        _to_ascii(settings.business_name),
        _to_ascii(settings.business_address),
        f"Tel: {_to_ascii(settings.business_phone)} Email: {_to_ascii(settings.business_email)}",
        "",
        payer_name,
        client_address_line,
        f"Tel: {_to_ascii(client_phone)}",
        "",
        "Receipt",
        "",
        "Items and Payments",
        "Items | Details | Amount",
        f"{session_display}, {_to_ascii(description)}",
        provider_line,
        f"Invoice #{invoice_id}-P01",
        f"Diagnosis: {diagnosis_line}",
        f"Special Notes: {special_notes_line}",
        f"${amount_display}",
        f"Subtotal: ${amount_display}",
        f"Payer Total: ${amount_display}",
        "",
        "Payments",
        f"{session_display} {payment_mode_line}",
        payer_name,
        "",
        (
            f"{_to_ascii(settings.business_name)} - {_to_ascii(settings.business_phone)} - "
            f"{_to_ascii(settings.business_email)} - Printed at: {issued_display}"
        ),
    ]

    content_parts = ["BT", "/F1 12 Tf", "50 760 Td"]
    for idx, line in enumerate(lines):
        if idx > 0:
            content_parts.append("0 -18 Td")
        content_parts.append(f"({_pdf_escape(line)}) Tj")
    content_parts.append("ET")
    content = "\n".join(content_parts)
    content_bytes = content.encode("latin-1", "replace")

    obj_1 = b"<< /Type /Catalog /Pages 2 0 R >>"
    obj_2 = b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>"
    obj_3 = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    obj_4 = (
        f"<< /Length {len(content_bytes)} >>\n".encode("ascii")
        + b"stream\n"
        + content_bytes
        + b"\nendstream"
    )
    obj_5 = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    objects = [obj_1, obj_2, obj_3, obj_4, obj_5]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def write_invoice_pdf(
    *,
    invoice_id: int,
    client_name: str | None,
    client_address: str | None,
    client_phone: str,
    amount_cents: int,
    currency: str,
    description: str,
    diagnosis: str | None = None,
    session_start_at: datetime | None = None,
    therapist_name: str | None = None,
    therapist_license_number: str | None = None,
    payment_mode: str | None = None,
    special_notes: str | None = None,
    issued_at: datetime | None = None,
) -> str:
    output_path = write_basic_invoice_pdf_file(
        invoice_id=invoice_id,
        client_name=client_name,
        client_address=client_address,
        client_phone=client_phone,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        diagnosis=diagnosis,
        session_start_at=session_start_at,
        therapist_name=therapist_name,
        therapist_license_number=therapist_license_number,
        payment_mode=payment_mode,
        special_notes=special_notes,
        issued_at=issued_at,
    )
    _ = output_path
    return build_invoice_pdf_url(invoice_id)


def write_basic_invoice_pdf_file(
    *,
    invoice_id: int,
    client_name: str | None,
    client_address: str | None,
    client_phone: str,
    amount_cents: int,
    currency: str,
    description: str,
    diagnosis: str | None = None,
    session_start_at: datetime | None = None,
    therapist_name: str | None = None,
    therapist_license_number: str | None = None,
    payment_mode: str | None = None,
    special_notes: str | None = None,
    issued_at: datetime | None = None,
) -> Path:
    pdf_bytes = build_invoice_pdf_bytes(
        invoice_id=invoice_id,
        client_name=client_name,
        client_address=client_address,
        client_phone=client_phone,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        diagnosis=diagnosis,
        session_start_at=session_start_at,
        therapist_name=therapist_name,
        therapist_license_number=therapist_license_number,
        payment_mode=payment_mode,
        special_notes=special_notes,
        issued_at=issued_at,
    )
    output_path = invoice_pdf_path(invoice_id)
    output_path.write_bytes(pdf_bytes)
    return output_path
