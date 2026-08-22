from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFormLayout

from app.main_window import MainWindow
from instrument import E5071C, InstrumentCommandError

TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp"


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
        settings = FakeSettings({"connection/last_ip_address": "192.0.2.10"})
        window = MainWindow(settings=settings)

        self.assertEqual(window.ip_edit.text(), "192.0.2.10")
        self.assertEqual(
            window.resource_edit.text(),
            "TCPIP0::192.0.2.10::5025::SOCKET",
        )
        window.close()
        window.deleteLater()

    def test_window_reports_v04_version(self) -> None:
        window = MainWindow(settings=FakeSettings())

        self.assertIn("V0.4", window.windowTitle())

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

    def test_setup_page_uses_current_version_neutral_labels(self) -> None:
        window = MainWindow(settings=FakeSettings())

        tab_labels = [window.tabs.tabText(index) for index in range(window.tabs.count())]
        self.assertIn("Setup", tab_labels)
        self.assertFalse(
            any(label.startswith("V") and label.endswith("Setup") for label in tab_labels)
        )
        self.assertEqual(window.v02_setup_group.title(), "Measurement Setup")

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

    def test_measurement_tools_page_replaces_dut_marker_readout(self) -> None:
        window = MainWindow(settings=FakeSettings())

        tab_labels = [window.tabs.tabText(index) for index in range(window.tabs.count())]
        self.assertIn("Measurement Tools", tab_labels)
        self.assertNotIn("DUT Measurement", tab_labels)
        self.assertEqual(window.dut_group.title(), "Measurement Tools")
        self.assertEqual(window.display_data_mem_button.text(), "Display Data & Mem")
        self.assertEqual(window.copy_data_to_mem_button.text(), "Data -> Mem: Trace 1-3")
        self.assertFalse(hasattr(window, "sweep_read_markers_button"))
        self.assertFalse(hasattr(window, "marker_table"))
        self.assertFalse(hasattr(window, "judgement_text"))

        window.close()
        window.deleteLater()

    def test_measurement_tools_page_exposes_configurable_screen_capture(self) -> None:
        window = MainWindow(settings=FakeSettings())

        self.assertEqual(window.capture_name_edit.text(), "screen_capture")
        self.assertEqual(window.capture_format_combo.currentText(), "PNG")
        self.assertTrue(window.capture_timestamp_checkbox.isChecked())
        self.assertIn("SmithPilot", window.capture_pc_folder_edit.text())
        self.assertEqual(window.capture_browse_button.text(), "Browse")
        self.assertFalse(hasattr(window, "capture_save_vna_checkbox"))
        self.assertEqual(window.capture_vna_folder_edit.text(), "D:\\SmithPilot\\Images")
        window._set_connected(True, mock=True)
        self.assertTrue(window.capture_vna_folder_edit.isEnabled())
        self.assertEqual(window.capture_screen_button.text(), "Capture Screen")

        row_labels = [
            window.capture_form.itemAt(row, QFormLayout.LabelRole).widget().text()
            for row in range(window.capture_form.rowCount())
            if window.capture_form.itemAt(row, QFormLayout.LabelRole) is not None
            and window.capture_form.itemAt(row, QFormLayout.LabelRole).widget() is not None
        ]
        self.assertLess(row_labels.index("VNA Folder:"), row_labels.index("Save To PC:"))

        window.capture_name_edit.setText("B34 before match")
        window.capture_pc_folder_edit.setText("C:\\Captures")
        window.capture_vna_folder_edit.setText("D:\\Custom\\Images")

        class FixedDateTime:
            @classmethod
            def now(cls) -> FixedDateTime:
                return cls()

            def strftime(self, _format: str) -> str:
                return "20260821_183012"

        with patch("app.main_window.datetime", FixedDateTime):
            pc_path = window._screen_capture_pc_path()
        self.assertEqual(str(pc_path), "C:\\Captures\\B34_before_match_20260821_183012.png")
        self.assertEqual(
            window._screen_capture_vna_path(pc_path.name),
            "D:\\Custom\\Images\\B34_before_match_20260821_183012.png",
        )

        window.close()
        window.deleteLater()

    def test_screen_capture_folders_are_loaded_from_settings(self) -> None:
        settings = FakeSettings(
            {
                "capture/vna_folder": "D:\\Last\\Images",
                "capture/pc_folder": "C:\\Last\\Captures",
            }
        )
        window = MainWindow(settings=settings)

        self.assertEqual(window.capture_vna_folder_edit.text(), "D:\\Last\\Images")
        self.assertEqual(window.capture_pc_folder_edit.text(), "C:\\Last\\Captures")

        window.close()
        window.deleteLater()

    def test_screen_capture_folders_are_saved_when_editing_finishes(self) -> None:
        settings = FakeSettings()
        window = MainWindow(settings=settings)

        window.capture_vna_folder_edit.setText("D:\\Custom\\Images")
        window.capture_pc_folder_edit.setText("C:\\Custom\\Captures")
        window.capture_vna_folder_edit.editingFinished.emit()
        window.capture_pc_folder_edit.editingFinished.emit()

        self.assertEqual(settings.value("capture/vna_folder"), "D:\\Custom\\Images")
        self.assertEqual(settings.value("capture/pc_folder"), "C:\\Custom\\Captures")

        window.close()
        window.deleteLater()

    def test_browsed_screen_capture_folder_is_saved(self) -> None:
        settings = FakeSettings()
        window = MainWindow(settings=settings)
        window._set_connected(True, mock=True)

        with patch(
            "app.main_window.QFileDialog.getExistingDirectory",
            return_value="C:\\Browsed\\Captures",
        ):
            window.capture_browse_button.click()

        self.assertEqual(window.capture_pc_folder_edit.text(), "C:\\Browsed\\Captures")
        self.assertEqual(settings.value("capture/pc_folder"), "C:\\Browsed\\Captures")

        window.close()
        window.deleteLater()

    def test_measurement_tools_capture_screen_saves_local_file_and_vna_copy(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        output_path = TEST_TMP_ROOT / "B34_capture.png"
        self.addCleanup(lambda: output_path.unlink(missing_ok=True))
        output_path.unlink(missing_ok=True)
        events: list[tuple[str, str]] = []
        settings = FakeSettings()
        window = MainWindow(settings=settings)
        driver = E5071C(
            mock=True, log_callback=lambda kind, message: events.append((kind, message))
        )
        driver.connect()
        events.clear()
        window.driver = driver
        window._set_connected(True, mock=True)

        window.capture_name_edit.setText("B34 capture")
        window.capture_timestamp_checkbox.setChecked(False)
        window.capture_pc_folder_edit.setText(str(TEST_TMP_ROOT))
        window.capture_vna_folder_edit.setText("D:\\Custom\\Images")
        window.capture_screen_button.click()

        deadline = time.monotonic() + 2.0
        while window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

        self.assertIsNone(window.worker)
        self.assertTrue(output_path.read_bytes().startswith(b"\x89PNG"))
        tx = [message for kind, message in events if kind == "TX"]
        self.assertIn(':MMEM:STOR:IMAG "D:\\Custom\\Images\\B34_capture.png"', tx)
        self.assertIn(':MMEM:TRAN? "D:\\Custom\\Images\\B34_capture.png"', tx)
        self.assertNotIn(':MMEM:DEL "D:\\Custom\\Images\\B34_capture.png"', tx)
        self.assertIn("Screen captured to", window.capture_status_label.text())
        self.assertIn("VNA copy saved", window.capture_status_label.text())
        self.assertEqual(settings.value("capture/vna_folder"), "D:\\Custom\\Images")
        self.assertEqual(settings.value("capture/pc_folder"), str(TEST_TMP_ROOT))

        window.close()
        window.deleteLater()

    def test_measurement_tools_capture_failure_updates_status(self) -> None:
        window = MainWindow(settings=FakeSettings())
        driver = E5071C(mock=True)
        driver.connect()
        window.driver = driver
        window._set_connected(True, mock=True)
        window.capture_name_edit.setText("failed capture")
        window.capture_timestamp_checkbox.setChecked(False)
        window.capture_pc_folder_edit.setText(str(TEST_TMP_ROOT))
        window.capture_vna_folder_edit.setText("D:\\SmithPilot\\Images")

        with (
            patch.object(
                driver,
                "capture_screen_image",
                side_effect=InstrumentCommandError("simulated capture failure"),
            ),
            patch("app.main_window.QMessageBox.warning"),
        ):
            window.capture_screen_button.click()
            deadline = time.monotonic() + 2.0
            while window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()

        self.assertIsNone(window.worker)
        self.assertEqual(
            window.capture_status_label.text(),
            "Capture failed: simulated capture failure",
        )

        window.close()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
