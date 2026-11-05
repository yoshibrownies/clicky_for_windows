import os

# Tests never open real windows; Qt renders into memory.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    """One QApplication for the whole run (Qt allows only one per process)."""
    return QApplication.instance() or QApplication([])
