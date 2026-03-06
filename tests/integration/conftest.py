import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless BGA credentials are set."""
    if not (os.environ.get("BGA_USERNAME") and os.environ.get("BGA_PASSWORD")):
        skip = pytest.mark.skip(reason="BGA_USERNAME and BGA_PASSWORD not set")
        for item in items:
            if "integration" in str(item.fspath):
                item.add_marker(skip)
