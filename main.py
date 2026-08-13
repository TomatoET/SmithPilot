from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


APP_ICON_DIR = Path(__file__).resolve().parent / "assets" / "app_icons"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SmithPilot")
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
