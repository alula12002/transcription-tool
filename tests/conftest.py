"""Shared test fixtures and setup."""

import shutil
from pathlib import Path


def pytest_configure(config):
    """Clear the refine cache before the test session.

    The refiner caches refined sections to disk for resumability.
    If cache files exist from a previous run, tests that use mock
    clients will get cache hits instead of calling the mock, causing
    assertion failures on captured calls.
    """
    cache_dir = Path(__file__).resolve().parent.parent / "temp_audio" / "refine_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
