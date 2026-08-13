from __future__ import annotations

import unittest
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


class FakeSettings:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values = dict(initial or {})

    def value(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def setValue(self, key: str, value: str) -> None:
        self.values[key] = value

    def sync(self) -> None:
        pass


class MainWindowSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_ip_address_is_loaded_from_settings(self) -> None:
        settings = FakeSettings({"connection/last_ip_address": "169.254.74.22"})
        window = MainWindow(settings=settings)

        self.assertEqual(window.ip_edit.text(), "169.254.74.22")
        self.assertEqual(
            window.resource_edit.text(),
            "TCPIP0::169.254.74.22::inst0::INSTR",
        )
        window.close()
        window.deleteLater()

    def test_ip_address_is_saved_when_editing_finishes(self) -> None:
        settings = FakeSettings()
        window = MainWindow(settings=settings)

        window.ip_edit.setText("192.168.0.10")
        window._remember_ip_address()

        self.assertEqual(settings.value("connection/last_ip_address"), "192.168.0.10")
        window.close()
        window.deleteLater()

    def test_calibration_page_separates_manual_ecal_and_state(self) -> None:
        window = MainWindow(settings=FakeSettings())

        self.assertEqual(window.calibration_tabs.count(), 3)
        self.assertEqual(window.calibration_tabs.tabText(0), "Mechanical SOLT")
        self.assertEqual(window.calibration_tabs.tabText(1), "Electronic ECal")
        self.assertEqual(window.calibration_tabs.tabText(2), "State")
        self.assertEqual(window.run_cal_step_button.text(), "Run Selected Step")
        self.assertEqual(window.run_ecal_button.text(), "Run 2-Port ECal")
        self.assertEqual(window.save_state_button.text(), "Save State")

        window.close()
        window.deleteLater()

    def test_ecal_page_uses_fixed_two_port_calibration(self) -> None:
        window = MainWindow(settings=FakeSettings())

        self.assertEqual(window.ecal_ports_label.text(), "Port 1 - Port 2")
        self.assertFalse(hasattr(window, "ecal_port1_spin"))
        self.assertFalse(hasattr(window, "ecal_port2_spin"))

        window.close()
        window.deleteLater()

    def test_port_extension_page_uses_three_port_choices(self) -> None:
        window = MainWindow(settings=FakeSettings())

        self.assertEqual(window._selected_port_extension_ports(), (1,))
        self.assertEqual(window.port_extension_port1_radio.text(), "Port 1")
        self.assertEqual(window.port_extension_port2_radio.text(), "Port 2")
        self.assertEqual(window.port_extension_all_radio.text(), "All")

        window.port_extension_port2_radio.setChecked(True)
        self.assertEqual(window._selected_port_extension_ports(), (2,))

        window.port_extension_all_radio.setChecked(True)
        self.assertEqual(window._selected_port_extension_ports(), (1, 2))

        window.close()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
