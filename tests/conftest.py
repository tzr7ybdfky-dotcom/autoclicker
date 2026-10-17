import os

# GUI-тесты без экрана: окна рисуются в памяти, реальные клики не отправляются.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["autoclicker-tests"])
    from autoclicker.gui.theme import apply_theme

    apply_theme(app)
    yield app
