"""Render a sample receipt PDF to confirm the LaTeX (tectonic) path works.

Also warms tectonic's support-bundle cache so the first real preview is fast.
Usage: uv run python scripts/warm_tectonic.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.invoice_generation import render_invoice_pdf_bytes  # noqa: E402

print(f"INVOICE_RENDERER={settings.invoice_renderer} ENGINE={settings.invoice_latex_engine}")

pdf = render_invoice_pdf_bytes(
    invoice_id=0,
    client_id=0,
    client_name="Preview Client",
    client_address="123 Sample Road, Hong Kong",
    client_phone="+85212345678",
    amount_cents=150000,
    currency="HKD",
    description="Physiotherapy Session Receipt (45 minutes)",
    diagnosis="Sample diagnosis",
    session_start_at=datetime(2026, 4, 28, 5, 0, tzinfo=timezone.utc),
    therapist_name="Cindy Yuen Ying Chau",
    therapist_license_number="PT102941",
    payment_mode="Cash",
    special_notes="-",
    issued_at=datetime.now(timezone.utc),
)

out = Path(__file__).resolve().parents[1] / "tectonic_sample.pdf"
out.write_bytes(pdf)
kind = "LaTeX (polished)" if len(pdf) > 40_000 else "BASIC fallback (plain)"
print(f"Rendered {len(pdf)} bytes -> {kind}")
print(f"Wrote {out}")
