"""Tests for therapist stamp file resolution (invoice LaTeX)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.invoice_latex import _find_stamp_file


@pytest.fixture
def stamp_dir_layout(tmp_path: Path) -> Path:
    """Minimal template + stamps mirroring repo naming styles."""
    tex = tmp_path / "receipt.tex"
    tex.write_text("% stub\n", encoding="utf-8")
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    (stamps / "Ava.jpeg").write_bytes(b"")
    (stamps / "Marco.jpeg").write_bytes(b"")
    (stamps / "Cindy Yuen Ying Chau.jpeg").write_bytes(b"")
    (stamps / "avishek_majumder.jpeg").write_bytes(b"")
    return tex


def test_stamp_spaced_full_name_case_insensitive(stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    found = _find_stamp_file("Dr. Cindy Yuen Ying Chau")
    assert found is not None
    assert found.name == "Cindy Yuen Ying Chau.jpeg"


def test_stamp_partial_first_name_in_file(stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    found = _find_stamp_file("Ava Chen")
    assert found is not None
    assert found.name == "Ava.jpeg"


def test_stamp_underscore_slug_filename(stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    found = _find_stamp_file("Avishek Majumder")
    assert found is not None
    assert found.name == "avishek_majumder.jpeg"


def test_stamp_therapist_single_token_matches_first_name_file(
    stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    found = _find_stamp_file("Marco")
    assert found is not None
    assert found.name == "Marco.jpeg"


def test_stamp_longer_therapist_than_partial_file(stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    found = _find_stamp_file("Dr Marco Luis Silva")
    assert found is not None
    assert found.name == "Marco.jpeg"


def test_stamp_no_token_prefix_match_returns_none(stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    assert _find_stamp_file("Evangeline Smith") is None


def test_stamp_no_middle_token_match_without_subsequence(stamp_dir_layout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """File lists first names; therapist with different first word should not match."""
    monkeypatch.setattr(settings, "invoice_latex_template_path", str(stamp_dir_layout))
    assert _find_stamp_file("John Ava Smith") is None
