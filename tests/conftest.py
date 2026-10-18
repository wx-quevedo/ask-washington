"""Shared test setup.

Query translation calls the real LLM, so it is off for the whole suite; the translation
tests use a simulated model instead.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True, scope="session")
def no_real_query_translation():
    settings = get_settings()
    saved = settings.query_translation
    settings.query_translation = False
    yield
    settings.query_translation = saved
