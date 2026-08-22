from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import APP_VERSION
from app.vna_workflow import (
    BAND_PRESETS_PATH,
    build_two_port_calibration_steps,
    builtin_band_presets,
    default_band_presets,
    default_ecal_plan,
    default_trace_setup,
)
from instrument import E5071C, InstrumentCommandError, InstrumentIdentity
from utils.logger import LogEntry, format_log_entry

FREQUENCY_UNITS = {
    "Hz": 1.0,
    "kHz": 1_000.0,
    "MHz": 1_000_000.0,
    "GHz": 1_000_000_000.0,
}


class InstrumentWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self._operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    driver_log = Signal(str, str)
    LAST_IP_ADDRESS_KEY = "connection/last_ip_address"
    LAST_CAPTURE_VNA_FOLDER_KEY = "capture/vna_folder"
    LAST_CAPTURE_PC_FOLDER_KEY = "capture/pc_folder"

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"SmithPilot {APP_VERSION} - E5071C VNA Workflow")
        self.settings = settings or QSettings()
        self.driver: E5071C | None = None
        self.worker: InstrumentWorker | None = None
        self.log_entries: list[LogEntry] = []
        self._connected = False
        self._busy = False
        self.band_preset_load_error = ""
        self.band_presets: list[object] = []
        self._load_band_presets()
        self.calibration_steps = list(build_two_port_calibration_steps())
        self.ecal_plan = default_ecal_plan()
        self.current_calibration_step = 0

        self._build_ui()
        self._load_saved_ip_address()
        self._load_capture_folders()
        self._connect_signals()
        self._refresh_resource()
        self._apply_band_preset()
        if self.band_preset_load_error:
            self.v02_setup_status_label.setText(self.band_preset_load_error)
            self._append_log("Warning", self.band_preset_load_error)
        self._refresh_enabled_state()
        self.statusBar().showMessage("Disconnected")

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        title = QLabel(f"SmithPilot {APP_VERSION}\nE5071C VNA Workflow")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(title)

        self.connection_group = self._build_connection_group()
        self.sweep_group = self._build_sweep_group()
        self.sweep_test_group = self._build_sweep_test_group()
        self.console_group = self._build_console_group()
        self.log_group = self._build_log_group()
        self.v02_setup_group = self._build_v02_setup_group()
        self.calibration_group = self._build_calibration_group()
        self.port_extension_group = self._build_port_extension_group()
        self.dut_group = self._build_dut_group()

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        connection_tab = QWidget()
        connection_layout = QGridLayout(connection_tab)
        connection_layout.setHorizontalSpacing(10)
        connection_layout.setVerticalSpacing(10)
        connection_layout.addWidget(self.connection_group, 0, 0)
        connection_layout.addWidget(self.sweep_group, 0, 1)
        connection_layout.addWidget(self.sweep_test_group, 1, 0)
        connection_layout.addWidget(self.console_group, 1, 1)
        connection_layout.setColumnStretch(0, 1)
        connection_layout.setColumnStretch(1, 1)
        self.tabs.addTab(connection_tab, "Connection")

        setup_tab = QWidget()
        setup_layout = QVBoxLayout(setup_tab)
        setup_layout.addWidget(self.v02_setup_group)
        setup_layout.addStretch(1)
        self.tabs.addTab(setup_tab, "Setup")

        calibration_tab = QWidget()
        calibration_layout = QVBoxLayout(calibration_tab)
        calibration_layout.addWidget(self.calibration_group)
        self.tabs.addTab(calibration_tab, "Calibration")

        extension_tab = QWidget()
        extension_layout = QVBoxLayout(extension_tab)
        extension_layout.addWidget(self.port_extension_group)
        extension_layout.addStretch(1)
        self.tabs.addTab(extension_tab, "Port Extension")

        dut_tab = QWidget()
        dut_layout = QVBoxLayout(dut_tab)
        dut_layout.addWidget(self.dut_group)
        self.tabs.addTab(dut_tab, "Measurement Tools")

        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.addWidget(self.log_group)
        self.tabs.addTab(log_tab, "Log")
        self._apply_styles()

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("Instrument Connection")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("Example: 192.168.0.10")
        self.resource_edit = QLineEdit()
        self.resource_edit.setReadOnly(True)
        self.mock_checkbox = QCheckBox("Use Mock Instrument")

        form.addRow("IP Address:", self.ip_edit)
        form.addRow("Resource:", self.resource_edit)
        form.addRow("", self.mock_checkbox)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.disconnect_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.connection_state_label = QLabel("\u25cf Disconnected")
        self.connection_state_label.setObjectName("disconnectedStatus")
        layout.addWidget(self.connection_state_label)

        identity_form = QFormLayout()
        self.manufacturer_value = QLabel("-")
        self.model_value = QLabel("-")
        self.serial_value = QLabel("-")
        self.firmware_value = QLabel("-")
        identity_form.addRow("Manufacturer:", self.manufacturer_value)
        identity_form.addRow("Model:", self.model_value)
        identity_form.addRow("Serial Number:", self.serial_value)
        identity_form.addRow("Firmware:", self.firmware_value)
        layout.addLayout(identity_form)

        return group

    def _build_sweep_group(self) -> QGroupBox:
        group = QGroupBox("Sweep Setup")
        layout = QVBoxLayout(group)

        validator = QDoubleValidator(0.0, 1_000_000_000_000.0, 12, self)

        self.start_frequency_edit = QLineEdit("1.8")
        self.start_frequency_edit.setValidator(validator)
        self.start_unit_combo = self._unit_combo(default="GHz")
        self.stop_frequency_edit = QLineEdit("2.0")
        self.stop_frequency_edit.setValidator(validator)
        self.stop_unit_combo = self._unit_combo(default="GHz")
        self.points_spin = QSpinBox()
        self.points_spin.setRange(2, 20001)
        self.points_spin.setValue(201)

        form = QFormLayout()
        form.addRow(
            "Start Frequency:", self._with_unit(self.start_frequency_edit, self.start_unit_combo)
        )
        form.addRow(
            "Stop Frequency:", self._with_unit(self.stop_frequency_edit, self.stop_unit_combo)
        )
        form.addRow("Points:", self.points_spin)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.read_sweep_button = QPushButton("Read From VNA")
        self.apply_sweep_button = QPushButton("Apply To VNA")
        button_row.addWidget(self.read_sweep_button)
        button_row.addWidget(self.apply_sweep_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.sweep_result_label = QLabel("Requested: -\nActual: -")
        self.sweep_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.apply_status_label = QLabel("")
        layout.addWidget(self.sweep_result_label)
        layout.addWidget(self.apply_status_label)

        return group

    def _build_sweep_test_group(self) -> QGroupBox:
        group = QGroupBox("Sweep Test")
        layout = QVBoxLayout(group)
        self.single_sweep_button = QPushButton("Single Sweep")
        self.single_sweep_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self.single_sweep_button)
        layout.addStretch(1)
        return group

    def _build_console_group(self) -> QGroupBox:
        group = QGroupBox("SCPI Console")
        layout = QVBoxLayout(group)
        form = QFormLayout()
        self.scpi_command_edit = QLineEdit("*IDN?")
        form.addRow("SCPI Command:", self.scpi_command_edit)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.scpi_send_button = QPushButton("Send")
        button_row.addWidget(self.scpi_send_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Communication Log")
        layout = QVBoxLayout(group)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Time, TX, RX, Error, and Connection events appear here.")
        layout.addWidget(self.log_text)

        button_row = QHBoxLayout()
        self.clear_log_button = QPushButton("Clear Log")
        self.save_log_button = QPushButton("Save Log")
        button_row.addWidget(self.clear_log_button)
        button_row.addWidget(self.save_log_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_v02_setup_group(self) -> QGroupBox:
        group = QGroupBox("Measurement Setup")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.band_combo = QComboBox()
        self._populate_band_combo()
        self.apply_band_button = QPushButton("Apply Band Preset")
        self.reload_band_button = QPushButton("Reload Presets")

        band_row = QHBoxLayout()
        band_row.addWidget(self.band_combo, 1)
        band_row.addWidget(self.apply_band_button)
        band_row.addWidget(self.reload_band_button)
        form.addRow("Band Preset:", self._wrap_layout(band_row))

        self.marker_edit = QLineEdit("1.92, 1.95, 1.98")
        self.marker_unit_combo = self._unit_combo(default="GHz")
        form.addRow("Markers:", self._with_unit(self.marker_edit, self.marker_unit_combo))
        layout.addLayout(form)

        self.trace_plan_label = QLabel(
            "Trace 1: S11 Smith\nTrace 2: S22 Smith\nTrace 3: S21 Log Mag"
        )
        self.trace_plan_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.trace_plan_label)

        button_row = QHBoxLayout()
        self.configure_v02_button = QPushButton("Configure Analyzer")
        self.read_v02_button = QPushButton("Read Analyzer Setup")
        button_row.addWidget(self.configure_v02_button)
        button_row.addWidget(self.read_v02_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.v02_setup_status_label = QLabel("")
        layout.addWidget(self.v02_setup_status_label)
        return group

    def _build_calibration_group(self) -> QGroupBox:
        group = QGroupBox("Calibration")
        layout = QVBoxLayout(group)

        self.calibration_tabs = QTabWidget()
        self.calibration_tabs.addTab(self._build_mechanical_calibration_tab(), "Mechanical SOLT")
        self.calibration_tabs.addTab(self._build_electronic_calibration_tab(), "Electronic ECal")
        self.calibration_tabs.addTab(self._build_state_tab(), "State")
        layout.addWidget(self.calibration_tabs)

        if self.cal_step_list.count() > 0:
            self.cal_step_list.setCurrentRow(0)
            self._on_calibration_step_selected(0)
        return group

    def _build_mechanical_calibration_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self.cal_kit_edit = QLineEdit("85032F")
        form.addRow("Cal Kit:", self.cal_kit_edit)
        layout.addLayout(form)

        self.cal_step_list = QListWidget()
        self._refresh_calibration_steps()
        layout.addWidget(self.cal_step_list)

        self.cal_instruction_label = QLabel("")
        self.cal_instruction_label.setWordWrap(True)
        self.cal_instruction_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.cal_instruction_label)

        button_row = QHBoxLayout()
        self.run_cal_step_button = QPushButton("Run Selected Step")
        self.next_cal_step_button = QPushButton("Select Next")
        self.cancel_cal_button = QPushButton("Cancel Cal")
        button_row.addWidget(self.run_cal_step_button)
        button_row.addWidget(self.next_cal_step_button)
        button_row.addWidget(self.cancel_cal_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        return tab

    def _build_electronic_calibration_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        module_form = QFormLayout()
        ecal_module_row = QHBoxLayout()
        self.ecal_module_combo = QComboBox()
        self.refresh_ecal_button = QPushButton("Refresh ECal")
        self.select_ecal_button = QPushButton("Select ECal")
        ecal_module_row.addWidget(self.ecal_module_combo, 1)
        ecal_module_row.addWidget(self.refresh_ecal_button)
        ecal_module_row.addWidget(self.select_ecal_button)
        module_form.addRow("ECal Module:", self._wrap_layout(ecal_module_row))
        layout.addLayout(module_form)

        ecal_form = QFormLayout()
        self.ecal_auto_orientation_checkbox = QCheckBox("Auto Orientation")
        self.ecal_auto_orientation_checkbox.setChecked(self.ecal_plan.auto_orientation)
        self.ecal_ports_label = QLabel("Port 1 - Port 2")
        self.ecal_ports_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ecal_form.addRow("", self.ecal_auto_orientation_checkbox)
        ecal_form.addRow("ECal Ports:", self.ecal_ports_label)
        layout.addLayout(ecal_form)

        ecal_buttons = QHBoxLayout()
        self.run_ecal_button = QPushButton("Run 2-Port ECal")
        self.ecal_confidence_check_button = QPushButton("Confidence Check")
        ecal_buttons.addWidget(self.run_ecal_button)
        ecal_buttons.addWidget(self.ecal_confidence_check_button)
        ecal_buttons.addStretch(1)
        layout.addLayout(ecal_buttons)

        self.ecal_status_label = QLabel("Connect ECal by USB, then refresh the list.")
        self.ecal_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.ecal_status_label)
        layout.addStretch(1)

        return tab

    def _build_state_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        state_form = QFormLayout()
        self.state_name_edit = QLineEdit("smithpilot_v02")
        self.save_type_combo = QComboBox()
        self.save_type_combo.addItem("All: State + Cal + Trace", "CDST")
        self.save_type_combo.addItem("State + Cal", "CST")
        self.save_type_combo.addItem("State Only", "STAT")
        self.save_type_combo.addItem("State + Trace", "DST")
        state_form.addRow("State Name:", self.state_name_edit)
        state_form.addRow("Save Type:", self.save_type_combo)
        layout.addLayout(state_form)

        state_buttons = QHBoxLayout()
        self.save_state_button = QPushButton("Save State")
        self.recall_state_button = QPushButton("Recall State")
        state_buttons.addWidget(self.save_state_button)
        state_buttons.addWidget(self.recall_state_button)
        state_buttons.addStretch(1)
        layout.addLayout(state_buttons)
        layout.addStretch(1)

        return tab

    def _build_port_extension_group(self) -> QGroupBox:
        group = QGroupBox("Auto Port Extension")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        port_row = QHBoxLayout()
        self.port_extension_button_group = QButtonGroup(self)
        self.port_extension_port1_radio = QRadioButton("Port 1")
        self.port_extension_port2_radio = QRadioButton("Port 2")
        self.port_extension_all_radio = QRadioButton("All")
        self.port_extension_port1_radio.setChecked(True)
        for button in (
            self.port_extension_port1_radio,
            self.port_extension_port2_radio,
            self.port_extension_all_radio,
        ):
            self.port_extension_button_group.addButton(button)
            port_row.addWidget(button)
        port_row.addStretch(1)
        self.port_extension_method_combo = QComboBox()
        self.port_extension_method_combo.addItems(["CSPN", "AMKR", "USPN"])
        self.include_loss_checkbox = QCheckBox("Include Loss")
        self.include_loss_checkbox.setChecked(True)
        self.adjust_mismatch_checkbox = QCheckBox("Adjust Mismatch")
        form.addRow("Ports:", self._wrap_layout(port_row))
        form.addRow("Method:", self.port_extension_method_combo)
        form.addRow("", self.include_loss_checkbox)
        form.addRow("", self.adjust_mismatch_checkbox)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.configure_port_extension_button = QPushButton("Configure")
        self.measure_port_extension_button = QPushButton("Measure OPEN")
        self.read_port_extension_button = QPushButton("Read Result")
        button_row.addWidget(self.configure_port_extension_button)
        button_row.addWidget(self.measure_port_extension_button)
        button_row.addWidget(self.read_port_extension_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.port_extension_result_label = QLabel("Delay: -\nLoss: -")
        self.port_extension_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.port_extension_result_label)
        return group

    def _build_dut_group(self) -> QGroupBox:
        group = QGroupBox("Measurement Tools")
        layout = QVBoxLayout(group)

        trace_memory_group = QGroupBox("Trace Memory")
        trace_memory_layout = QVBoxLayout(trace_memory_group)

        button_row = QHBoxLayout()
        self.display_data_mem_button = QPushButton("Display Data & Mem")
        self.copy_data_to_mem_button = QPushButton("Data -> Mem: Trace 1-3")
        button_row.addWidget(self.display_data_mem_button)
        button_row.addWidget(self.copy_data_to_mem_button)
        button_row.addStretch(1)
        trace_memory_layout.addLayout(button_row)

        self.measurement_tools_status_label = QLabel("Ready")
        self.measurement_tools_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        trace_memory_layout.addWidget(self.measurement_tools_status_label)

        layout.addWidget(trace_memory_group)

        screen_capture_group = QGroupBox("Screen Capture")
        screen_capture_layout = QVBoxLayout(screen_capture_group)
        self.capture_form = QFormLayout()

        self.capture_name_edit = QLineEdit("screen_capture")
        self.capture_format_combo = QComboBox()
        self.capture_format_combo.addItems(["PNG", "BMP"])
        self.capture_timestamp_checkbox = QCheckBox("Add timestamp")
        self.capture_timestamp_checkbox.setChecked(True)

        self.capture_vna_folder_edit = QLineEdit("D:\\SmithPilot\\Images")
        self.capture_pc_folder_edit = QLineEdit(str(self._default_capture_folder()))
        self.capture_browse_button = QPushButton("Browse")
        pc_folder_row = QHBoxLayout()
        pc_folder_row.addWidget(self.capture_pc_folder_edit, 1)
        pc_folder_row.addWidget(self.capture_browse_button)

        self.capture_form.addRow("File Name:", self.capture_name_edit)
        self.capture_form.addRow("Format:", self.capture_format_combo)
        self.capture_form.addRow("", self.capture_timestamp_checkbox)
        self.capture_form.addRow("VNA Folder:", self.capture_vna_folder_edit)
        self.capture_form.addRow("Save To PC:", self._wrap_layout(pc_folder_row))
        screen_capture_layout.addLayout(self.capture_form)

        capture_button_row = QHBoxLayout()
        self.capture_screen_button = QPushButton("Capture Screen")
        capture_button_row.addWidget(self.capture_screen_button)
        capture_button_row.addStretch(1)
        screen_capture_layout.addLayout(capture_button_row)

        self.capture_status_label = QLabel("Ready")
        self.capture_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        screen_capture_layout.addWidget(self.capture_status_label)

        layout.addWidget(screen_capture_group)
        layout.addStretch(1)
        return group

    def _connect_signals(self) -> None:
        self.driver_log.connect(self._append_log)
        self.ip_edit.textChanged.connect(self._refresh_resource)
        self.ip_edit.editingFinished.connect(self._remember_ip_address)
        self.mock_checkbox.toggled.connect(self._on_mock_toggled)
        self.connect_button.clicked.connect(self._connect_to_instrument)
        self.disconnect_button.clicked.connect(self._disconnect_from_instrument)
        self.read_sweep_button.clicked.connect(self._read_sweep)
        self.apply_sweep_button.clicked.connect(self._apply_sweep)
        self.single_sweep_button.clicked.connect(self._single_sweep)
        self.scpi_send_button.clicked.connect(self._send_scpi)
        self.scpi_command_edit.returnPressed.connect(self._send_scpi)
        self.clear_log_button.clicked.connect(self._clear_log)
        self.save_log_button.clicked.connect(self._save_log)
        self.apply_band_button.clicked.connect(self._apply_band_preset)
        self.reload_band_button.clicked.connect(self._reload_band_presets)
        self.configure_v02_button.clicked.connect(self._configure_v02_measurement)
        self.read_v02_button.clicked.connect(self._read_sweep)
        self.cal_kit_edit.editingFinished.connect(self._refresh_calibration_steps)
        self.cal_step_list.currentRowChanged.connect(self._on_calibration_step_selected)
        self.run_cal_step_button.clicked.connect(self._run_selected_calibration_step)
        self.next_cal_step_button.clicked.connect(self._select_next_calibration_step)
        self.cancel_cal_button.clicked.connect(self._cancel_calibration)
        self.save_state_button.clicked.connect(self._save_instrument_state)
        self.recall_state_button.clicked.connect(self._recall_instrument_state)
        self.refresh_ecal_button.clicked.connect(self._refresh_ecal_modules)
        self.select_ecal_button.clicked.connect(self._select_ecal_module)
        self.run_ecal_button.clicked.connect(self._run_two_port_ecal)
        self.ecal_confidence_check_button.clicked.connect(self._run_ecal_confidence_check)
        self.configure_port_extension_button.clicked.connect(self._configure_port_extension)
        self.measure_port_extension_button.clicked.connect(self._measure_port_extension)
        self.read_port_extension_button.clicked.connect(self._read_port_extension_result)
        self.display_data_mem_button.clicked.connect(self._display_traces_data_and_memory)
        self.copy_data_to_mem_button.clicked.connect(self._copy_traces_data_to_memory)
        self.capture_vna_folder_edit.editingFinished.connect(self._remember_capture_folders)
        self.capture_pc_folder_edit.editingFinished.connect(self._remember_capture_folders)
        self.capture_browse_button.clicked.connect(self._browse_capture_folder)
        self.capture_screen_button.clicked.connect(self._capture_screen_to_pc)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f5f7fa; }
            QLabel#titleLabel {
                font-size: 20px;
                font-weight: 700;
                color: #172033;
                padding-bottom: 4px;
            }
            QLabel#sectionTitle {
                font-size: 13px;
                font-weight: 700;
                color: #172033;
                padding-top: 8px;
            }
            QGroupBox {
                border: 1px solid #c6ccd6;
                border-radius: 6px;
                margin-top: 8px;
                padding: 10px;
                font-weight: 600;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
                border: 1px solid #b9c0cc;
                border-radius: 4px;
                padding: 4px;
                background: #ffffff;
            }
            QPushButton {
                border: 1px solid #8b97a8;
                border-radius: 4px;
                padding: 6px 12px;
                background: #edf1f6;
            }
            QPushButton:hover { background: #e2e8f0; }
            QPushButton:disabled { color: #7d8794; background: #eef0f3; }
            QLabel#connectedStatus { color: #1f7a3f; font-weight: 700; }
            QLabel#mockStatus { color: #936100; font-weight: 700; }
            QLabel#disconnectedStatus { color: #a32323; font-weight: 700; }
            """
        )

    def _unit_combo(self, default: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(FREQUENCY_UNITS.keys())
        combo.setCurrentText(default)
        return combo

    def _with_unit(self, edit: QLineEdit, combo: QComboBox) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(combo)
        return wrapper

    def _wrap_layout(self, child_layout: QHBoxLayout) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        while child_layout.count():
            item = child_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                layout.addWidget(widget)
        return wrapper

    def _refresh_resource(self) -> None:
        if self.mock_checkbox.isChecked():
            self.resource_edit.setText("MOCK::E5071C::INSTR")
            return
        self.resource_edit.setText(E5071C.build_resource(self.ip_edit.text()))

    def _load_saved_ip_address(self) -> None:
        value = self.settings.value(self.LAST_IP_ADDRESS_KEY, "")
        if value:
            self.ip_edit.setText(str(value).strip())

    def _remember_ip_address(self) -> None:
        ip_address = self.ip_edit.text().strip()
        if not ip_address:
            return
        self.settings.setValue(self.LAST_IP_ADDRESS_KEY, ip_address)
        self.settings.sync()

    def _load_capture_folders(self) -> None:
        vna_folder = str(self.settings.value(self.LAST_CAPTURE_VNA_FOLDER_KEY, "") or "").strip()
        pc_folder = str(self.settings.value(self.LAST_CAPTURE_PC_FOLDER_KEY, "") or "").strip()
        if vna_folder:
            self.capture_vna_folder_edit.setText(vna_folder)
        if pc_folder:
            self.capture_pc_folder_edit.setText(pc_folder)

    def _remember_capture_folders(self) -> None:
        vna_folder = self.capture_vna_folder_edit.text().strip()
        pc_folder = self.capture_pc_folder_edit.text().strip()
        if vna_folder:
            self.settings.setValue(self.LAST_CAPTURE_VNA_FOLDER_KEY, vna_folder)
        if pc_folder:
            self.settings.setValue(self.LAST_CAPTURE_PC_FOLDER_KEY, pc_folder)
        self.settings.sync()

    def _load_band_presets(self) -> None:
        try:
            self.band_presets = list(default_band_presets())
            self.band_preset_load_error = ""
        except (OSError, ValueError) as exc:
            self.band_presets = list(builtin_band_presets())
            self.band_preset_load_error = (
                f"Band preset file ignored; using built-in defaults. {exc}"
            )

    def _populate_band_combo(self) -> None:
        self.band_combo.clear()
        for band in self.band_presets:
            self.band_combo.addItem(band.name, band)

    def _reload_band_presets(self) -> None:
        current_name = self.band_combo.currentText().strip()
        self._load_band_presets()
        self._populate_band_combo()
        if current_name:
            index = self.band_combo.findText(current_name)
            if index >= 0:
                self.band_combo.setCurrentIndex(index)
        self._apply_band_preset()
        if self.band_preset_load_error:
            self.v02_setup_status_label.setText(self.band_preset_load_error)
            self._append_log("Warning", self.band_preset_load_error)
        else:
            self.v02_setup_status_label.setText(f"Band presets loaded: {BAND_PRESETS_PATH}")

    def _on_mock_toggled(self, enabled: bool) -> None:
        self.ip_edit.setEnabled(not enabled and not self._connected and not self._busy)
        self._refresh_resource()

    def _apply_band_preset(self) -> None:
        band = self.band_combo.currentData()
        if band is None:
            return
        self._set_frequency_controls(
            float(band.start_hz), self.start_frequency_edit, self.start_unit_combo
        )
        self._set_frequency_controls(
            float(band.stop_hz), self.stop_frequency_edit, self.stop_unit_combo
        )
        self.points_spin.setValue(int(band.points))
        marker_unit = self._best_unit(max(float(value) for value in band.marker_hz))
        self.marker_unit_combo.setCurrentText(marker_unit)
        self.marker_edit.setText(
            ", ".join(
                f"{float(value) / FREQUENCY_UNITS[marker_unit]:.12g}" for value in band.marker_hz
            )
        )
        self.v02_setup_status_label.setText(f"Preset applied: {band.name}")

    def _configure_v02_measurement(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        try:
            start_hz = self._read_frequency_hz(self.start_frequency_edit, self.start_unit_combo)
            stop_hz = self._read_frequency_hz(self.stop_frequency_edit, self.stop_unit_combo)
            marker_hz = self._read_marker_frequencies_hz()
            points = int(self.points_spin.value())
            if start_hz >= stop_hz:
                raise InstrumentCommandError("Start frequency must be less than stop frequency.")
        except InstrumentCommandError as exc:
            self._show_error(str(exc))
            return

        def operation() -> None:
            driver.configure_v02_measurement(
                start_hz=start_hz,
                stop_hz=stop_hz,
                points=points,
                marker_hz=marker_hz,
                traces=default_trace_setup(),
            )

        def on_success(_: object) -> None:
            self.v02_setup_status_label.setText("Analyzer setup applied.")
            self._show_status("Analyzer setup applied.")

        self._run_worker(operation, on_success)

    def _refresh_calibration_steps(self) -> None:
        cal_kit = self.cal_kit_edit.text().strip() if hasattr(self, "cal_kit_edit") else "85032F"
        self.calibration_steps = list(build_two_port_calibration_steps(cal_kit or "85032F"))
        if not hasattr(self, "cal_step_list"):
            return
        current = self.cal_step_list.currentRow()
        self.cal_step_list.clear()
        for index, step in enumerate(self.calibration_steps, 1):
            self.cal_step_list.addItem(f"{index}. {step.title}")
        if self.calibration_steps:
            row = min(max(current, 0), len(self.calibration_steps) - 1)
            self.cal_step_list.setCurrentRow(row)
            if hasattr(self, "cal_instruction_label"):
                self._on_calibration_step_selected(row)

    def _on_calibration_step_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.calibration_steps):
            if hasattr(self, "cal_instruction_label"):
                self.cal_instruction_label.setText("")
            return
        self.current_calibration_step = row
        step = self.calibration_steps[row]
        self.cal_instruction_label.setText(step.instruction)

    def _select_next_calibration_step(self) -> None:
        if not self.calibration_steps:
            return
        next_row = min(self.current_calibration_step + 1, len(self.calibration_steps) - 1)
        self.cal_step_list.setCurrentRow(next_row)

    def _run_selected_calibration_step(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        row = self.cal_step_list.currentRow()
        if row < 0 or row >= len(self.calibration_steps):
            self._show_error("Select a calibration step first.")
            return
        step = self.calibration_steps[row]
        if step.requires_user_confirmation and not self._confirm_step(step.title, step.instruction):
            return

        def operation() -> None:
            if step.action == "start_two_port_solt":
                driver.start_two_port_solt_calibration(
                    cal_kit=self.cal_kit_edit.text().strip() or "85032F"
                )
            elif step.action.startswith("measure_"):
                driver.acquire_calibration_standard(step.standard, step.ports)
            elif step.action == "save_calibration":
                driver.save_calibration()
            else:
                raise InstrumentCommandError(f"Unsupported calibration step: {step.action}")

        def on_success(_: object) -> None:
            self._show_status(f"Calibration step complete: {step.title}")
            self._append_log("Connection", f"Calibration step complete: {step.title}")
            self._select_next_calibration_step()

        self._run_worker(operation, on_success)

    def _cancel_calibration(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        if not self._confirm_step(
            "Cancel Calibration", "Cancel the current calibration collection?"
        ):
            return

        def operation() -> None:
            driver.cancel_calibration()

        def on_success(_: object) -> None:
            self._show_status("Calibration collection cancelled.")

        self._run_worker(operation, on_success)

    def _save_instrument_state(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        name = self.state_name_edit.text().strip()
        if not name:
            self._show_error("State name is required.")
            return
        message = (
            "This saves analyzer state on the E5071C and can overwrite an existing file "
            "with the same name. Continue?"
        )
        if not self._confirm_step("Save Analyzer State", message):
            return
        save_type = str(self.save_type_combo.currentData() or "CDST")

        def operation() -> None:
            driver.save_state(name, save_type=save_type)

        def on_success(_: object) -> None:
            self._show_status(f"Analyzer state saved: {name}")

        self._run_worker(operation, on_success)

    def _recall_instrument_state(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        name = self.state_name_edit.text().strip()
        if not name:
            self._show_error("State name is required.")
            return
        message = "Recall changes the current analyzer setup. Continue?"
        if not self._confirm_step("Recall Analyzer State", message):
            return

        def operation() -> None:
            driver.recall_state(name)

        def on_success(_: object) -> None:
            self._show_status(f"Analyzer state recalled: {name}")

        self._run_worker(operation, on_success)

    def _refresh_ecal_modules(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        def operation() -> object:
            return driver.list_ecal_modules()

        def on_success(result: object) -> None:
            modules = list(result)
            self.ecal_module_combo.clear()
            self.ecal_module_combo.addItems(str(module) for module in modules)
            if modules:
                self.ecal_status_label.setText(f"{len(modules)} ECal module(s) found.")
                self._show_status("ECal module list refreshed.")
            else:
                self.ecal_status_label.setText("No ECal module found over USB.")
                self._show_status("No ECal module found.")

        self._run_worker(operation, on_success)

    def _select_ecal_module(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        ecal_id = self.ecal_module_combo.currentText().strip()
        if not ecal_id:
            self._show_error("Refresh and select an ECal module first.")
            return

        def operation() -> None:
            driver.select_ecal_module(ecal_id)

        def on_success(_: object) -> None:
            self.ecal_status_label.setText(f"Selected ECal: {ecal_id}")
            self._show_status(f"ECal selected: {ecal_id}")

        self._run_worker(operation, on_success)

    def _run_two_port_ecal(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        ports = self.ecal_plan.ports
        message = (
            f"Connect the ECal module between VNA Port {ports[0]} and Port {ports[1]}. "
            "Once ECal starts, wait for completion before sending other commands."
        )
        if not self._confirm_step("Run 2-Port ECal", message):
            return
        auto_orientation = self.ecal_auto_orientation_checkbox.isChecked()

        def operation() -> None:
            ecal_id = self.ecal_module_combo.currentText().strip()
            if ecal_id:
                driver.select_ecal_module(ecal_id)
            driver.set_ecal_auto_orientation(auto_orientation)
            driver.perform_two_port_ecal(ports)

        def on_success(_: object) -> None:
            self.ecal_status_label.setText(f"2-Port ECal complete for Port {ports[0]}-{ports[1]}.")
            self._show_status("2-Port ECal complete.")

        self._run_worker(operation, on_success)

    def _run_ecal_confidence_check(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        message = "Run the ECal confidence check on the current calibration?"
        if not self._confirm_step("ECal Confidence Check", message):
            return

        def operation() -> None:
            driver.perform_ecal_confidence_check()

        def on_success(_: object) -> None:
            self.ecal_status_label.setText("ECal confidence check complete.")
            self._show_status("ECal confidence check complete.")

        self._run_worker(operation, on_success)

    def _configure_port_extension(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        ports = self._selected_port_extension_ports()
        method = self.port_extension_method_combo.currentText()
        include_loss = self.include_loss_checkbox.isChecked()
        adjust_mismatch = self.adjust_mismatch_checkbox.isChecked()

        def operation() -> None:
            driver.configure_auto_port_extension_ports(
                ports=ports,
                include_loss=include_loss,
                adjust_mismatch=adjust_mismatch,
                method=method,
            )

        def on_success(_: object) -> None:
            self._show_status(f"Auto Port Extension configured for {self._format_ports(ports)}.")

        self._run_worker(operation, on_success)

    def _measure_port_extension(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        ports = self._selected_port_extension_ports()
        if len(ports) == 1:
            message = (
                f"Connect OPEN standard at the Port {ports[0]} extension reference plane, "
                "then measure?"
            )
        else:
            message = (
                "Connect OPEN standards at both Port 1 and Port 2 extension reference planes, "
                "then measure?"
            )
        if not self._confirm_step("Measure Auto Port Extension", message):
            return

        def operation() -> object:
            driver.measure_auto_port_extension_ports(ports=ports, standard="OPEN")
            return driver.get_port_extension_results(ports=ports)

        def on_success(result: object) -> None:
            self._set_port_extension_results(list(result))
            self._show_status(f"Auto Port Extension measured for {self._format_ports(ports)}.")

        self._run_worker(operation, on_success)

    def _read_port_extension_result(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        ports = self._selected_port_extension_ports()

        def operation() -> object:
            return driver.get_port_extension_results(ports=ports)

        def on_success(result: object) -> None:
            self._set_port_extension_results(list(result))
            self._show_status(f"Auto Port Extension result read for {self._format_ports(ports)}.")

        self._run_worker(operation, on_success)

    def _display_traces_data_and_memory(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        def operation() -> None:
            driver.display_traces_data_and_memory(traces=(1, 2, 3))

        def on_success(_: object) -> None:
            message = "Data and memory traces displayed for Trace 1-3."
            self.measurement_tools_status_label.setText(message)
            self._show_status(message)

        self._run_worker(operation, on_success)

    def _copy_traces_data_to_memory(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        def operation() -> None:
            driver.copy_traces_data_to_memory(traces=(1, 2, 3))

        def on_success(_: object) -> None:
            message = "Trace 1-3 data copied to memory."
            self.measurement_tools_status_label.setText(message)
            self._show_status(message)

        self._run_worker(operation, on_success)

    def _browse_capture_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Capture Folder",
            self.capture_pc_folder_edit.text().strip() or str(self._default_capture_folder()),
        )
        if folder:
            self.capture_pc_folder_edit.setText(folder)
            self._remember_capture_folders()

    def _capture_screen_to_pc(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return
        try:
            image_format = self.capture_format_combo.currentText().strip().upper()
            pc_path = self._screen_capture_pc_path()
            vna_path = self._screen_capture_vna_path(pc_path.name)
        except InstrumentCommandError as exc:
            self._show_error(str(exc))
            return

        self._remember_capture_folders()

        if pc_path.exists():
            reply = QMessageBox.question(
                self,
                "Overwrite Capture",
                f"{pc_path} already exists.\n\nOverwrite this file?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.capture_status_label.setText("Capture canceled.")
                return

        self.capture_status_label.setText("Capturing screen...")

        def operation() -> tuple[str, str]:
            image = driver.capture_screen_image(
                image_format=image_format,
                vna_path=vna_path,
                keep_vna_copy=True,
            )
            pc_path.parent.mkdir(parents=True, exist_ok=True)
            pc_path.write_bytes(image)
            return str(pc_path), vna_path

        def on_success(result: object) -> None:
            local_path, saved_vna_path = result
            message = f"Screen captured to {local_path}"
            if saved_vna_path:
                message = f"{message}; VNA copy saved to {saved_vna_path}"
            self.capture_status_label.setText(message)
            self._show_status(message)

        def on_failure(message: str) -> None:
            self.capture_status_label.setText(f"Capture failed: {message}")

        self._run_worker(operation, on_success, on_failure=on_failure)

    def _connect_to_instrument(self) -> None:
        if self.worker is not None:
            self._show_status("Operation already in progress.")
            return

        mock = self.mock_checkbox.isChecked()
        ip_address = self.ip_edit.text().strip()
        if not mock and not ip_address:
            self._show_error("IP address is required for real E5071C mode.")
            return
        if ip_address:
            self._remember_ip_address()

        driver = E5071C(
            ip_address=ip_address,
            resource=self.resource_edit.text().strip(),
            timeout_ms=10000,
            mock=mock,
            log_callback=self.driver_log.emit,
        )

        def operation() -> tuple[E5071C, InstrumentIdentity, str]:
            identity = driver.connect()
            return driver, identity, driver.last_system_error

        def on_success(result: object) -> None:
            connected_driver, identity, system_error = result
            self.driver = connected_driver
            self.resource_edit.setText(connected_driver.resource)
            self._set_identity(identity)
            self._set_connected(True, mock=connected_driver.mock)
            if system_error and not E5071C.system_error_is_clear(system_error):
                self._show_status(f"Connected with instrument error: {system_error}")
            else:
                self._show_status("Instrument connected successfully.")

        self._run_worker(operation, on_success)

    def _disconnect_from_instrument(self) -> None:
        if self.worker is not None:
            self._show_status("Wait for the current operation to finish before disconnecting.")
            return
        if self.driver is not None:
            self.driver.disconnect()
        self.driver = None
        self._set_identity(InstrumentIdentity())
        self._set_connected(False)
        self._show_status("Disconnected")

    def _read_sweep(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        def operation() -> dict[str, float | int]:
            return {
                "start": driver.get_start_frequency(),
                "stop": driver.get_stop_frequency(),
                "points": driver.get_sweep_points(),
            }

        def on_success(result: object) -> None:
            data = result
            self._set_frequency_controls(
                float(data["start"]), self.start_frequency_edit, self.start_unit_combo
            )
            self._set_frequency_controls(
                float(data["stop"]), self.stop_frequency_edit, self.stop_unit_combo
            )
            self.points_spin.setValue(int(data["points"]))
            self.sweep_result_label.setText(
                "Requested: -\n"
                f"Actual: {self._format_hz(float(data['start']))}, "
                f"{self._format_hz(float(data['stop']))}, {int(data['points'])}"
            )
            self.apply_status_label.setText("Read complete")
            self._show_status("Sweep parameters read from VNA.")

        self._run_worker(operation, on_success)

    def _apply_sweep(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        try:
            requested_start = self._read_frequency_hz(
                self.start_frequency_edit, self.start_unit_combo
            )
            requested_stop = self._read_frequency_hz(self.stop_frequency_edit, self.stop_unit_combo)
            requested_points = int(self.points_spin.value())
            if requested_start >= requested_stop:
                raise InstrumentCommandError("Start frequency must be less than stop frequency.")
        except InstrumentCommandError as exc:
            self._show_error(str(exc))
            return

        def operation() -> dict[str, float | int]:
            driver.set_start_frequency(requested_start)
            driver.set_stop_frequency(requested_stop)
            driver.set_sweep_points(requested_points)
            return {
                "requested_start": requested_start,
                "requested_stop": requested_stop,
                "requested_points": requested_points,
                "actual_start": driver.get_start_frequency(),
                "actual_stop": driver.get_stop_frequency(),
                "actual_points": driver.get_sweep_points(),
            }

        def on_success(result: object) -> None:
            data = result
            actual_start = float(data["actual_start"])
            actual_stop = float(data["actual_stop"])
            actual_points = int(data["actual_points"])
            applied = (
                self._same_frequency(requested_start, actual_start)
                and self._same_frequency(requested_stop, actual_stop)
                and requested_points == actual_points
            )
            self.sweep_result_label.setText(
                "Requested: "
                f"{self._format_hz(requested_start)}, "
                f"{self._format_hz(requested_stop)}, {requested_points}\n"
                "Actual: "
                f"{self._format_hz(actual_start)}, "
                f"{self._format_hz(actual_stop)}, {actual_points}"
            )
            if applied:
                self.apply_status_label.setText("\u2713 Applied")
                self._show_status("Sweep parameters applied and verified.")
            else:
                self.apply_status_label.setText("Mismatch after readback")
                self._append_log("Error", "Requested sweep parameters do not match VNA readback.")
                self._show_status("Sweep parameter readback mismatch.")

        self._run_worker(operation, on_success)

    def _single_sweep(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        def operation() -> None:
            driver.trigger_single_sweep()

        def on_success(_: object) -> None:
            self._show_status("Single sweep complete.")

        self._run_worker(operation, on_success)

    def _send_scpi(self) -> None:
        driver = self._require_driver()
        if driver is None:
            return

        command = self.scpi_command_edit.text().strip()
        if not command:
            self._show_error("SCPI command is empty.")
            return

        def operation() -> str:
            if "?" in command:
                return driver.query(command)
            driver.write(command)
            system_error = driver.query_error()
            if not E5071C.system_error_is_clear(system_error):
                raise InstrumentCommandError(f"Instrument reported SCPI error: {system_error}")
            return f"Write accepted; SYST:ERR {system_error}"

        def on_success(result: object) -> None:
            self._show_status(str(result))

        self._run_worker(operation, on_success)

    def _run_worker(
        self,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        if self.worker is not None:
            self._show_status("Operation already in progress.")
            return

        self._set_busy(True)
        worker = InstrumentWorker(operation, self)
        self.worker = worker

        def handle_success(result: object) -> None:
            on_success(result)

        def handle_failure(message: str) -> None:
            if on_failure is not None:
                on_failure(message)
            self._show_error(message)
            if self.driver is not None and not self.driver.is_connected():
                self._set_identity(InstrumentIdentity())
                self._set_connected(False)

        def handle_finished() -> None:
            if self.worker is worker:
                self.worker = None
            worker.deleteLater()
            self._set_busy(False)

        worker.succeeded.connect(handle_success)
        worker.failed.connect(handle_failure)
        worker.finished.connect(handle_finished)
        worker.start()

    def _require_driver(self) -> E5071C | None:
        if self.driver is None or not self.driver.is_connected():
            self._show_error("Instrument disconnected.")
            return None
        return self.driver

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_enabled_state()

    def _set_connected(self, connected: bool, mock: bool = False) -> None:
        self._connected = connected
        if connected:
            if mock:
                self.connection_state_label.setText("\u25cf Connected (MOCK)")
                self.connection_state_label.setObjectName("mockStatus")
            else:
                self.connection_state_label.setText("\u25cf Connected")
                self.connection_state_label.setObjectName("connectedStatus")
        else:
            self.connection_state_label.setText("\u25cf Disconnected")
            self.connection_state_label.setObjectName("disconnectedStatus")
        self.connection_state_label.style().unpolish(self.connection_state_label)
        self.connection_state_label.style().polish(self.connection_state_label)
        self._refresh_enabled_state()

    def _refresh_enabled_state(self) -> None:
        connected = self._connected
        busy = self._busy
        mock = self.mock_checkbox.isChecked()

        self.connect_button.setEnabled(not connected and not busy)
        self.disconnect_button.setEnabled(connected and not busy)
        self.mock_checkbox.setEnabled(not connected and not busy)
        self.ip_edit.setEnabled(not connected and not busy and not mock)

        controls_enabled = connected and not busy
        self.sweep_group.setEnabled(controls_enabled)
        self.sweep_test_group.setEnabled(controls_enabled)
        self.console_group.setEnabled(controls_enabled)
        self.v02_setup_group.setEnabled(controls_enabled)
        self.calibration_group.setEnabled(controls_enabled)
        self.port_extension_group.setEnabled(controls_enabled)
        self.dut_group.setEnabled(controls_enabled)

    def _set_identity(self, identity: InstrumentIdentity) -> None:
        self.manufacturer_value.setText(identity.manufacturer or "-")
        self.model_value.setText(identity.model or "-")
        self.serial_value.setText(identity.serial_number or "-")
        self.firmware_value.setText(identity.firmware or "-")

    def _read_frequency_hz(self, edit: QLineEdit, combo: QComboBox) -> float:
        text = edit.text().strip()
        if not text:
            raise InstrumentCommandError("Frequency value is required.")
        value = float(text)
        hz = value * FREQUENCY_UNITS[combo.currentText()]
        if hz <= 0:
            raise InstrumentCommandError("Frequency must be greater than 0 Hz.")
        return hz

    def _set_frequency_controls(self, hz: float, edit: QLineEdit, combo: QComboBox) -> None:
        unit = self._best_unit(hz)
        combo.setCurrentText(unit)
        edit.setText(f"{hz / FREQUENCY_UNITS[unit]:.12g}")

    def _best_unit(self, hz: float) -> str:
        abs_hz = abs(hz)
        if abs_hz >= FREQUENCY_UNITS["GHz"]:
            return "GHz"
        if abs_hz >= FREQUENCY_UNITS["MHz"]:
            return "MHz"
        if abs_hz >= FREQUENCY_UNITS["kHz"]:
            return "kHz"
        return "Hz"

    def _format_hz(self, hz: float) -> str:
        unit = self._best_unit(hz)
        return f"{hz / FREQUENCY_UNITS[unit]:.12g} {unit}"

    def _same_frequency(self, requested_hz: float, actual_hz: float) -> bool:
        return math.isclose(requested_hz, actual_hz, rel_tol=1e-9, abs_tol=1.0)

    def _read_marker_frequencies_hz(self) -> tuple[float, ...]:
        text = self.marker_edit.text().strip()
        if not text:
            raise InstrumentCommandError("At least one marker frequency is required.")
        parts = [part for part in re.split(r"[,;\s]+", text) if part]
        if len(parts) > 10:
            raise InstrumentCommandError("E5071C supports up to 10 markers.")
        multiplier = FREQUENCY_UNITS[self.marker_unit_combo.currentText()]
        values: list[float] = []
        for part in parts:
            try:
                value = float(part) * multiplier
            except ValueError as exc:
                raise InstrumentCommandError(f"Invalid marker frequency: {part}") from exc
            if value <= 0:
                raise InstrumentCommandError("Marker frequencies must be greater than 0 Hz.")
            values.append(value)
        return tuple(values)

    def _confirm_step(self, title: str, message: str) -> bool:
        reply = QMessageBox.question(
            self,
            title,
            f"{message}\n\nRun this step now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _selected_port_extension_ports(self) -> tuple[int, ...]:
        if self.port_extension_all_radio.isChecked():
            return (1, 2)
        if self.port_extension_port2_radio.isChecked():
            return (2,)
        return (1,)

    @staticmethod
    def _format_ports(ports: tuple[int, ...]) -> str:
        if ports == (1, 2):
            return "Port 1 + Port 2"
        return f"Port {ports[0]}"

    def _set_port_extension_result(self, result: object) -> None:
        self.port_extension_result_label.setText(self._format_port_extension_result(result))

    def _set_port_extension_results(self, results: list[object]) -> None:
        if not results:
            self.port_extension_result_label.setText("No Port Extension result.")
            return
        self.port_extension_result_label.setText(
            "\n\n".join(self._format_port_extension_result(result) for result in results)
        )

    def _format_port_extension_result(self, result: object) -> str:
        delay_ps = float(result.delay_s) * 1e12
        return (
            f"Port {int(result.port)}\n"
            f"Delay: {delay_ps:.3f} ps\n"
            f"Loss1: {float(result.loss1_db):.3f} dB @ {self._format_hz(float(result.freq1_hz))}\n"
            f"Loss2: {float(result.loss2_db):.3f} dB @ {self._format_hz(float(result.freq2_hz))}"
        )

    @staticmethod
    def _default_capture_folder() -> Path:
        return Path.home() / "Documents" / "SmithPilot" / "Captures"

    def _screen_capture_pc_path(self) -> Path:
        folder_text = self.capture_pc_folder_edit.text().strip()
        if not folder_text:
            raise InstrumentCommandError("PC capture folder is required.")
        return Path(folder_text).expanduser() / self._screen_capture_file_name()

    def _screen_capture_vna_path(self, file_name: str) -> str:
        folder = self.capture_vna_folder_edit.text().strip().rstrip("\\/")
        if not folder:
            raise InstrumentCommandError("VNA capture folder is required.")
        path = f"{folder}\\{file_name}"
        E5071C._safe_vna_image_path(path)
        return path

    def _screen_capture_file_name(self) -> str:
        image_format = self.capture_format_combo.currentText().strip().lower()
        if image_format not in {"png", "bmp"}:
            raise InstrumentCommandError("Screen capture format must be PNG or BMP.")
        stem = self._screen_capture_stem()
        if self.capture_timestamp_checkbox.isChecked():
            stem = f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return f"{stem}.{image_format}"

    def _screen_capture_stem(self) -> str:
        text = self.capture_name_edit.text().strip()
        if not text:
            raise InstrumentCommandError("Screen capture file name is required.")
        name = PureWindowsPath(text).name.strip()
        suffix = PureWindowsPath(name).suffix.lower()
        if suffix in {".png", ".bmp"}:
            name = name[: -len(suffix)].strip()
        if not re.fullmatch(r"[A-Za-z0-9_. -]{1,80}", name):
            raise InstrumentCommandError(
                "Screen capture file name may contain letters, numbers, spaces, '.', '_', and '-'."
            )
        return name.replace(" ", "_")

    def _append_log(self, kind: str, message: str) -> None:
        entry = LogEntry.now(kind, message)
        self.log_entries.append(entry)
        self.log_text.appendPlainText(format_log_entry(entry))

    def _clear_log(self) -> None:
        self.log_entries.clear()
        self.log_text.clear()

    def _save_log(self) -> None:
        default_name = f"smithpilot_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Communication Log",
            default_name,
            "Text Files (*.txt);;All Files (*.*)",
        )
        if not path:
            return
        Path(path).write_text(self.log_text.toPlainText(), encoding="utf-8")
        self._show_status(f"Log saved to {path}")

    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _show_error(self, message: str) -> None:
        self._append_log("Error", message)
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "SmithPilot", message)
