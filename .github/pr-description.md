# Receipt PDF Preview Endpoint + Receipt Naming & Refactoring

This PR adds a **receipt preview endpoint** (`/api/v1/admin/invoices/preview`) that allows admins to generate and view receipt PDFs without persisting them to the database or sending WhatsApp messages. The preview uses the same validation and rendering logic as the finalized invoice generation, ensuring the preview matches the actual receipt. It also includes LaTeX engine improvements, proper receipt naming by appointment date, and refactoring to eliminate dead code paths.

## Summary

| Aspect | Details |
|--------|---------|
| PR Title | feat(invoice): add receipt PDF preview endpoint + receipt pdf naming |
| Author | @upadhyay-gif |
| Base Branch | dev |
| Head Branch | feat/invoicing-receipts |
| Files Changed | 6 files |
| Additions | 297 lines added |
| Deletions | 24 lines removed |
| Changes | New feature (preview endpoint) + refactoring + bug fixes + LaTeX improvements |

## Key Changes

1. **Receipt Preview Endpoint** (`/api/v1/admin/invoices/preview`)
   - New POST endpoint that renders a receipt PDF for preview without persisting
   - Streams PDF inline with `Content-Disposition: inline`
   - No database writes, no WhatsApp messages sent
   - Validates the same way as the `generate` endpoint
   - Uses placeholder invoice_id=0 since no record is created

2. **Extracted Field Resolution Logic**
   - Introduced `_ResolvedInvoiceFields` dataclass to centralize invoice field computation
   - Extracted `_resolve_invoice_fields()` function used by both `generate` and `preview`
   - Makes the business logic reusable and testable independently of persistence

3. **PDF Rendering Function**
   - New `render_invoice_pdf_bytes()` in `invoice_generation.py`
   - Returns bytes without persisting to storage
   - Cleans up temporary LaTeX files afterward
   - Uses same renderer path as full generation (LaTeX with basic fallback)

4. **Tectonic LaTeX Engine Improvements**
   - Fixed engine detection to use `Path(engine).stem.lower()` instead of string equality
   - Now handles absolute paths like `C:\Users\me\bin\tectonic.exe` correctly
   - Added `scripts/warm_tectonic.py` utility to pre-warm tectonic's cache and validate LaTeX path

5. **Receipt PDF Naming & Dating**
   - PDF filenames now respect appointment date via `session_start_at` or `issued_at` (spec 2.6)
   - Updated preview endpoint to use `invoice_filename(date_value=session_start_at)` for consistent naming
   - More semantically correct naming for session-based receipts

6. **Refactoring: Eliminate Dead Code Paths**
   - Removed dead `now()` fallbacks in receipt flow
   - `effective_session_start_at` is always set (Session.start_time is NOT NULL)
   - Pass appointment date directly so filename can never silently fall back to generation date
   - Payments-flow fallback (no session) and low-level service defaults intentionally left intact

## Test Coverage

- `test_preview_invoice_returns_pdf_without_persisting()` — confirms preview generates PDF without side effects
- `test_preview_invoice_applies_same_validation_as_generate()` — confirms preview validates inputs identically
