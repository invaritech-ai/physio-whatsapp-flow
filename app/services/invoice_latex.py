from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.services.invoice_documents import invoice_pdf_path


def _latex_escape(value: str | None) -> str:
    if value is None:
        return "-"
    escaped = value
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        escaped = escaped.replace(old, new)
    escaped = escaped.replace("\r\n", "\\\\").replace("\n", "\\\\")
    return escaped


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
    local = value.astimezone(_invoice_timezone())
    hour_12 = local.strftime("%I").lstrip("0") or "0"
    minute = local.strftime("%M")
    suffix = local.strftime("%p").lower()
    return f"{local.strftime('%B')} {local.day}, {local.year} - {hour_12}:{minute}{suffix}"


def _format_payment_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(_invoice_timezone())
    hour_12 = local.strftime("%I").lstrip("0") or "0"
    minute = local.strftime("%M")
    suffix = local.strftime("%p").lower()
    return f"{local.strftime('%A')} {local.strftime('%B')} {local.day}, {local.year} - {hour_12}:{minute}{suffix}"


def _currency_amount(amount_cents: int) -> str:
    return f"{amount_cents / 100:,.2f}"


def _resolve_template_path() -> Path:
    candidate = Path(settings.invoice_latex_template_path)
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _build_template_context(
    *,
    invoice_id: int,
    client_id: int,
    client_name: str | None,
    client_address: str | None,
    client_phone: str,
    amount_cents: int,
    description: str,
    diagnosis: str | None,
    session_start_at: datetime | None,
    therapist_name: str | None,
    therapist_license_number: str | None,
    payment_mode: str | None,
    special_notes: str | None,
    issued_at: datetime | None,
) -> dict[str, str]:
    printed_at = _format_invoice_datetime(issued_at or datetime.now(timezone.utc))
    session_at = _format_invoice_datetime(session_start_at)
    payment_at = _format_payment_datetime(session_start_at)
    payer_name = client_name or "Client"
    payment_label = payment_mode or "N/A"
    provider_line = f"{therapist_name or '-'}, License #{therapist_license_number or '-'}"
    return {
        "business_name": _latex_escape(settings.business_name),
        "business_address": _latex_escape(settings.business_address),
        "business_phone": _latex_escape(settings.business_phone),
        "business_email": _latex_escape(settings.business_email),
        "printed_at": _latex_escape(printed_at),
        "client_name": _latex_escape(payer_name),
        "client_address": _latex_escape(client_address or ""),
        "client_phone": _latex_escape(client_phone),
        "receipt_title": _latex_escape("Receipt"),
        "items_payments_title": _latex_escape("Items and Payments"),
        "item_datetime_line": _latex_escape(session_at),
        "item_description": _latex_escape(description),
        "provider_line": _latex_escape(provider_line),
        "invoice_number": _latex_escape(f"{invoice_id}-P{client_id:02d}"),
        "diagnosis_line": _latex_escape(diagnosis or ""),
        "special_notes_line": _latex_escape(special_notes or ""),
        "amount_display": _latex_escape(_currency_amount(amount_cents)),
        "payment_datetime_method": _latex_escape(f"{payment_at} {payment_label}"),
        "payment_payer_name": _latex_escape(payer_name),
    }


def _render_template(template_text: str, context: dict[str, str]) -> str:
    rendered = template_text
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _compile_latex(tex_file: Path, output_dir: Path) -> Path:
    engine = settings.invoice_latex_engine.strip() or "pdflatex"
    if shutil.which(engine) is None:
        raise RuntimeError(f"LaTeX engine '{engine}' not found in PATH")

    if engine == "tectonic":
        cmd = [engine, "--outdir", str(output_dir), str(tex_file)]
    else:
        cmd = [
            engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(output_dir),
            str(tex_file),
        ]

    result = subprocess.run(
        cmd,
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=settings.invoice_latex_timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-30:])
        raise RuntimeError(f"LaTeX compilation failed:\n{tail}")

    pdf_path = output_dir / f"{tex_file.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError("LaTeX compilation completed without producing PDF output")
    return pdf_path


def write_latex_invoice_pdf_file(
    *,
    invoice_id: int,
    client_id: int,
    client_name: str | None,
    client_address: str | None,
    client_phone: str,
    amount_cents: int,
    description: str,
    diagnosis: str | None,
    session_start_at: datetime | None,
    therapist_name: str | None,
    therapist_license_number: str | None,
    payment_mode: str | None,
    special_notes: str | None,
    issued_at: datetime | None,
) -> Path:
    template_path = _resolve_template_path()
    if not template_path.exists():
        raise RuntimeError(f"LaTeX template not found: {template_path}")

    context = _build_template_context(
        invoice_id=invoice_id,
        client_id=client_id,
        client_name=client_name,
        client_address=client_address,
        client_phone=client_phone,
        amount_cents=amount_cents,
        description=description,
        diagnosis=diagnosis,
        session_start_at=session_start_at,
        therapist_name=therapist_name,
        therapist_license_number=therapist_license_number,
        payment_mode=payment_mode,
        special_notes=special_notes,
        issued_at=issued_at,
    )
    rendered_tex = _render_template(
        template_path.read_text(encoding="utf-8"),
        context,
    )

    with tempfile.TemporaryDirectory(prefix=f"invoice-{invoice_id}-latex-") as tmp_dir:
        work_dir = Path(tmp_dir)
        tex_file = work_dir / f"invoice-{invoice_id}.tex"
        tex_file.write_text(rendered_tex, encoding="utf-8")
        compiled_pdf = _compile_latex(tex_file, work_dir)
        destination = invoice_pdf_path(invoice_id)
        destination.write_bytes(compiled_pdf.read_bytes())
        return destination
