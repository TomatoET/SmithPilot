from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import __version__
from app.main_window import MainWindow

APP_ICON_DIR = Path(__file__).resolve().parent / "assets" / "app_icons"


def check_visa_backend() -> int:
    try:
        import pyvisa

        resource_manager = pyvisa.ResourceManager("@py")
        resource_manager.close()
    except Exception as exc:
        print(f"PyVISA-py backend check failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    if "--check-visa-backend" in sys.argv:
        return check_visa_backend()

    app = QApplication(sys.argv)
    app.setApplicationName("SmithPilot")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("SmithPilot")

    app_icon = QIcon(str(APP_ICON_DIR / "app-icon.ico"))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    window_icon = QIcon(str(APP_ICON_DIR / "window-icon.ico"))
    if not window_icon.isNull():
        window.setWindowIcon(window_icon)
    window.resize(1160, 820)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
