"""Fixtures."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture
def fuelio_csv() -> str:
    """Synthetic Fuelio export."""
    return (FIXTURES / "fuelio_sample.csv").read_text(encoding="utf-8")
