from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.services.invoice_latex import write_latex_invoice_pdf_file


def test_write_latex_invoice_pdf_file_uses_canonical_filename(monkeypatch, tmp_path: Path) -> None:
    from app.services import invoice_latex

    template = tmp_path / "receipt.tex"
    template.write_text("stub", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(invoice_latex.settings, "invoice_storage_dir", str(out_dir))

    monkeypatch.setattr(invoice_latex, "_resolve_template_path", lambda: template)
    monkeypatch.setattr(invoice_latex, "_build_template_context", lambda **kwargs: {})
    monkeypatch.setattr(invoice_latex, "_render_template", lambda text, context: "hello")
    monkeypatch.setattr(invoice_latex, "_find_stamp_file", lambda therapist_name: None)
    monkeypatch.setattr(invoice_latex, "_logo_file", lambda: None)

    def _fake_compile(_tex_file: Path, work_dir: Path) -> Path:
        pdf = work_dir / "invoice-99.pdf"
        pdf.write_bytes(b"%PDF-1.4\nstub")
        return pdf

    monkeypatch.setattr(invoice_latex, "_compile_latex", _fake_compile)

    issued_at = datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc)
    destination = write_latex_invoice_pdf_file(
        invoice_id=99,
        client_id=3,
        client_name="Jane Doe",
        client_address="1 Test Road",
        client_phone="+85290000000",
        amount_cents=10000,
        description="Physio",
        diagnosis=None,
        session_start_at=issued_at,
        therapist_name="Dr. Test",
        therapist_license_number="PT-1",
        payment_mode="Cash",
        special_notes=None,
        issued_at=issued_at,
    )

    assert destination.name == "jane-doe_2026-05-06_MOVEMENT_PHYSIOTHERAPY_RECEIPT_99.pdf"
    assert destination.exists()
