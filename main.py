from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SmithPilot")
    app.setOrganizationName("SmithPilot")

    window = MainWindow()
    window.resize(1160, 820)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
