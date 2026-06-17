from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.services.invoice_documents import invoice_pdf_path

logger = logging.getLogger(__name__)


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
    return f"{local.strftime('%A')} {local.strftime('%B')} {local.day}, {local.year}"


def _strip_dr_prefix(name: str | None) -> str:
    """Remove leading 'Dr.' / 'Dr ' honorific from a therapist name."""
    if not name:
        return "-"
    import re
    return re.sub(r"^Dr\.?\s+", "", name, flags=re.IGNORECASE).strip() or name


def _currency_amount(amount_cents: int) -> str:
    return f"{amount_cents / 100:,.2f}"


def _resolve_template_path() -> Path:
    candidate = Path(settings.invoice_latex_template_path)
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _stamps_dir() -> Path:
    return _resolve_template_path().parent / "stamps"


def _logo_file() -> Path | None:
    candidate = _resolve_template_path().parent / "logo.png"
    if candidate.is_file():
        return candidate
    return None


_STAMP_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".pdf"})


def _name_tokens(s: str) -> list[str]:
    """Normalize a display name or filename stem to lowercase word tokens."""
    if not s or not str(s).strip():
        return []
    t = str(s).replace("_", " ").replace("-", " ").lower()
    return [p for p in t.split() if p]


def _token_list_is_prefix(short: list[str], long: list[str]) -> bool:
    """True if short equals the first len(short) tokens of long."""
    if len(short) > len(long):
        return False
    return long[: len(short)] == short


def _therapist_tokens_for_stamp(therapist_name: str) -> list[str]:
    clean = _strip_dr_prefix(therapist_name)
    if clean == "-":
        clean = therapist_name.strip()
    return _name_tokens(clean)


def _find_stamp_file(therapist_name: str | None) -> Path | None:
    """
    Find a stamp image for the therapist.

    Matches full names, slug-style stems (underscores), and partial names on
    either side: e.g. file ``Ava.jpeg`` with therapist ``Dr. Ava Chen``, or
    ``Cindy Yuen Ying Chau.jpeg`` with the same string case-insensitively.
    """
    if not therapist_name:
        return None
    therapist_tokens = _therapist_tokens_for_stamp(therapist_name)
    if not therapist_tokens:
        return None

    stamps = _stamps_dir()
    if not stamps.is_dir():
        return None

    candidates: list[tuple[int, int, int, str, Path]] = []
    # Sort key: exact before prefix; then closest token-count gap; then more
    # overlapping tokens; stable tie-break on filename.
    for path in sorted(stamps.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in _STAMP_EXTENSIONS:
            continue
        stem_tokens = _name_tokens(path.stem)
        if not stem_tokens:
            continue

        if stem_tokens == therapist_tokens:
            candidates.append((0, 0, 0, path.name.lower(), path))
            continue

        file_extends_therapist = _token_list_is_prefix(stem_tokens, therapist_tokens)
        therapist_extends_file = _token_list_is_prefix(therapist_tokens, stem_tokens)
        if not (file_extends_therapist or therapist_extends_file):
            continue

        common = min(len(stem_tokens), len(therapist_tokens))
        length_delta = abs(len(stem_tokens) - len(therapist_tokens))
        candidates.append((1, length_delta, -common, path.name.lower(), path))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][4]


def _stamp_block(stamp_filename: str | None) -> str:
    """Return the LaTeX snippet for the stamp overlay, or empty if no stamp."""
    if not stamp_filename:
        return "% no stamp available"
    return (
        r"\node[opacity=1.0, rotate=-5] "
        r"at ([yshift=14mm, xshift=20mm]therapist.north west) {"
        "\n"
        rf"    \includegraphics[width=40mm]{{{stamp_filename}}}"
        "\n"
        r"};"
    )


def _logo_block(logo_filename: str | None) -> str:
    """Return the LaTeX snippet for the logo, or empty if no logo."""
    if not logo_filename:
        return "% no logo available"
    return (
        r"\node[anchor=north west] "
        r"at ([xshift=15mm,yshift=-15mm]current page.north west) {"
        "\n"
        rf"    \includegraphics[width=42mm,height=22mm,keepaspectratio]{{{logo_filename}}}"
        "\n"
        r"};"
    )


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
) -> dict[str, str]:
    session_at = _format_invoice_datetime(session_start_at)
    payment_date = _format_payment_datetime(session_start_at)
    payer_name = client_name or "Client"
    clean_therapist_name = _strip_dr_prefix(therapist_name)
    provider_line = f"{clean_therapist_name}, License #{therapist_license_number or '-'}"
    stamp_file = _find_stamp_file(therapist_name)
    logo_file = _logo_file()
    return {
        "logo_block": _logo_block(logo_file.name if logo_file else None),
        "business_name": _latex_escape(settings.business_name),
        "business_address": _latex_escape(settings.business_address),
        "business_phone": _latex_escape(settings.business_phone),
        "business_email": _latex_escape(settings.business_email),
        "client_name": _latex_escape(payer_name),
        "client_address": _latex_escape(client_address or "Sai Ying Pun, Hong Kong Island"),
        "client_phone": _latex_escape(client_phone),
        "receipt_title": _latex_escape("Receipt"),
        "items_payments_title": _latex_escape("Items and Payments"),
        "item_datetime_line": _latex_escape(session_at),
        "item_description": _latex_escape(description),
        "provider_line": _latex_escape(provider_line),
        "therapist_name_only": _latex_escape(clean_therapist_name),
        "invoice_number": _latex_escape(f"{invoice_id}-P{client_id:02d}"),
        "diagnosis_line": _latex_escape(diagnosis or ""),
        "special_notes_line": _latex_escape(special_notes or ""),
        "amount_display": _latex_escape(_currency_amount(amount_cents)),
        "payment_date": _latex_escape(payment_date),
        "payment_client_name": _latex_escape(payer_name),
        "stamp_block": _stamp_block(stamp_file.name if stamp_file else None),
    }


def _render_template(template_text: str, context: dict[str, str]) -> str:
    rendered = template_text
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _resolve_latex_engine() -> str:
    """Pick the first LaTeX engine available in PATH (preferred first, then fallbacks)."""
    preferred = (settings.invoice_latex_engine or "pdflatex").strip() or "pdflatex"
    candidates: list[str] = []
    for name in (
        preferred,
        "pdflatex",
        "tectonic",
        "xelatex",
        "lualatex",
    ):
        if name not in candidates:
            candidates.append(name)
    for engine in candidates:
        if shutil.which(engine):
            if engine != preferred:
                logger.warning(
                    "invoice_latex_engine %r not found in PATH; using %r instead",
                    preferred,
                    engine,
                )
            return engine
    raise RuntimeError(
        f"No LaTeX engine found in PATH (tried: {', '.join(candidates)})"
    )


def _compile_latex(tex_file: Path, output_dir: Path) -> Path:
    engine = _resolve_latex_engine()

    # Detect tectonic by the executable's base name so an absolute path
    # (e.g. C:\Users\me\bin\tectonic.exe) still uses tectonic's CLI flags.
    if Path(engine).stem.lower() == "tectonic":
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
    )
    rendered_tex = _render_template(
        template_path.read_text(encoding="utf-8"),
        context,
    )

    stamp_file = _find_stamp_file(therapist_name)
    logo_file = _logo_file()

    with tempfile.TemporaryDirectory(prefix=f"invoice-{invoice_id}-latex-") as tmp_dir:
        work_dir = Path(tmp_dir)
        if stamp_file:
            shutil.copy2(stamp_file, work_dir / stamp_file.name)
        if logo_file:
            shutil.copy2(logo_file, work_dir / logo_file.name)
        tex_file = work_dir / f"invoice-{invoice_id}.tex"
        tex_file.write_text(rendered_tex, encoding="utf-8")
        compiled_pdf = _compile_latex(tex_file, work_dir)
        destination = invoice_pdf_path(
            invoice_id=invoice_id,
            client_name=client_name,
            date_value=session_start_at or issued_at,
        )
        destination.write_bytes(compiled_pdf.read_bytes())
        return destination
