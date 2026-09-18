"""Ray, 2026-09-17: "fully native, no browser engine". The venv installs
PySide6-Essentials only, so QtWebEngine is not merely unused -- it is not
there to import. Installing the `PySide6` meta-package would turn this red."""

import importlib.util


def test_no_browser_engine_is_installed():
    assert importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None
    assert importlib.util.find_spec("PySide6.QtWebEngineCore") is None


def test_the_qt_modules_the_app_uses_are_installed():
    for name in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
                 "PySide6.QtNetwork"):
        assert importlib.util.find_spec(name) is not None, name
