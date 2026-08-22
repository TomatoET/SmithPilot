from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any

from instrument.base_vna import (
    BaseVNA,
    InstrumentCommandError,
    InstrumentConnectionError,
    InstrumentError,
    InstrumentIdentity,
    InstrumentSafetyError,
    InstrumentTimeoutError,
    LogCallback,
)

DEFAULT_TIMEOUT_MS = 10000


@dataclass(frozen=True)
class PortExtensionResult:
    port: int
    delay_s: float
    loss1_db: float
    loss2_db: float
    freq1_hz: float
    freq2_hz: float


@dataclass(frozen=True)
class MarkerResult:
    trace: str
    trace_number: int
    marker: int
    frequency_hz: float
    primary: float
    secondary: float


class E5071C(BaseVNA):
    """Agilent/Keysight E5071C VNA driver.

    All SCPI traffic used by SmithPilot is intentionally contained in this
    module. The UI talks to this driver only, never to PyVISA directly.
    """

    MOCK_IDN = "Agilent Technologies,E5071C,MOCK001,MOCK"

    _START_HEADERS = {
        "SENS:FREQ:STAR",
        "SENS:FREQ:START",
        "SENS1:FREQ:STAR",
        "SENS1:FREQ:START",
        "SENSE:FREQUENCY:START",
        "SENSE1:FREQUENCY:START",
    }
    _STOP_HEADERS = {
        "SENS:FREQ:STOP",
        "SENS1:FREQ:STOP",
        "SENSE:FREQUENCY:STOP",
        "SENSE1:FREQUENCY:STOP",
    }
    _POINT_HEADERS = {
        "SENS:SWE:POIN",
        "SENS:SWE:POINTS",
        "SENS1:SWE:POIN",
        "SENS1:SWE:POINTS",
        "SENSE:SWEEP:POINTS",
        "SENSE1:SWEEP:POINTS",
    }
    _INIT_CONT_HEADERS = {
        "INIT:CONT",
        "INIT1:CONT",
        "INITIATE:CONTINUOUS",
        "INITIATE1:CONTINUOUS",
    }
    _INIT_SINGLE_HEADERS = {
        "INIT",
        "INIT1",
        "INIT:IMM",
        "INIT1:IMM",
        "INITIATE",
        "INITIATE1",
        "INITIATE:IMMEDIATE",
        "INITIATE1:IMMEDIATE",
    }
    _TRIGGER_SOURCE_HEADERS = {
        "TRIG:SOUR",
        "TRIG:SEQ:SOUR",
        "TRIGGER:SOURCE",
        "TRIGGER:SEQUENCE:SOURCE",
    }

    def __init__(
        self,
        ip_address: str = "",
        resource: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        mock: bool = False,
        log_callback: LogCallback | None = None,
    ) -> None:
        self.ip_address = ip_address.strip()
        self.resource = (resource or self.build_resource(self.ip_address)).strip()
        self.timeout_ms = timeout_ms
        self.mock = mock
        self.log_callback = log_callback

        self._resource_manager: Any | None = None
        self._session: Any | None = None
        self._connected = False
        self.identity = InstrumentIdentity()
        self.last_system_error = ""

        self._mock_start_hz = 1_000_000_000.0
        self._mock_stop_hz = 2_000_000_000.0
        self._mock_points = 201
        self._mock_system_error = '+0,"No error"'
        self._mock_ecal_modules = ("N4431B 03605",)
        self._mock_selected_ecal = self._mock_ecal_modules[0]
        self._mock_port_extension: dict[int, PortExtensionResult] = {
            port: PortExtensionResult(port, 0.0, 0.0, 0.0, 0.0, 0.0) for port in range(1, 5)
        }
        self._mock_auto_port_extension_ports: set[int] = set()
        self._mock_trace_measurements: dict[int, str] = {1: "S11", 2: "S22", 3: "S21"}
        self._mock_markers: dict[tuple[int, int], float] = {}
        self._mock_screen_capture_format = "PNG"
        self._mock_vna_directories = {"d:"}

    @staticmethod
    def build_resource(ip_address: str) -> str:
        ip = ip_address.strip() or "<IP>"
        return f"TCPIP0::{ip}::5025::SOCKET"

    @staticmethod
    def build_vxi11_resource(ip_address: str) -> str:
        ip = ip_address.strip() or "<IP>"
        return f"TCPIP0::{ip}::inst0::INSTR"

    @staticmethod
    def system_error_is_clear(response: str) -> bool:
        code = response.split(",", 1)[0].strip()
        try:
            return int(float(code)) == 0
        except ValueError:
            return False

    def connect(self) -> InstrumentIdentity:
        if self._connected:
            return self.identity

        if self.mock:
            self._connected = True
            self._emit("Connection", "MOCK instrument selected; no VISA resource opened")
            idn = self.query_idn()
            self.identity = InstrumentIdentity.from_idn(idn)
            self.last_system_error = self.query_error()
            self._emit("Connection", "Mock instrument connected successfully")
            return self.identity

        if not self.ip_address or "<IP>" in self.resource:
            raise InstrumentConnectionError("IP address is required for real E5071C mode.")

        self._emit("Connection", "Connecting to E5071C...")
        try:
            import pyvisa
        except ImportError as exc:
            raise InstrumentConnectionError(
                "PyVISA is not installed. Run: pip install -r requirements.txt"
            ) from exc

        failures: list[tuple[str, InstrumentError]] = []
        original_resource = self.resource
        for resource in self._connection_resource_candidates():
            try:
                return self._connect_resource(pyvisa, resource)
            except InstrumentError as exc:
                failures.append((resource, exc))
                self._emit("Error", f"{resource}: {exc}")
                self._close_session()
                self._connected = False

        self.resource = original_resource
        raise InstrumentConnectionError(self._format_connection_failures(failures))

    def disconnect(self) -> None:
        self._close_session()
        if self._connected:
            self._emit("Connection", "Instrument disconnected")
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def query_idn(self) -> str:
        return self.query("*IDN?")

    def query_error(self) -> str:
        response = self.query("SYST:ERR?")
        self.last_system_error = response
        if not self.system_error_is_clear(response):
            self._emit("Error", f"SYST:ERR returned {response}")
        return response

    def write(self, command: str, check_error: bool = False) -> None:
        self._ensure_connected()
        command = self._clean_command(command)
        if "?" in command:
            raise InstrumentCommandError("write() received a query command.")
        self._ensure_safe_scpi(command)
        self._write_raw(command)
        if check_error:
            self._raise_if_system_error()

    def query(self, command: str) -> str:
        self._ensure_connected()
        command = self._clean_command(command)
        if "?" not in command:
            raise InstrumentCommandError("query() requires a SCPI command containing '?'.")
        self._ensure_safe_scpi(command)
        return self._query_raw(command)

    def set_start_frequency(self, freq_hz: float) -> None:
        self._validate_frequency(freq_hz, "Start frequency")
        self.write(f":SENS1:FREQ:STAR {freq_hz:.12g}", check_error=True)

    def set_stop_frequency(self, freq_hz: float) -> None:
        self._validate_frequency(freq_hz, "Stop frequency")
        self.write(f":SENS1:FREQ:STOP {freq_hz:.12g}", check_error=True)

    def set_sweep_points(self, points: int) -> None:
        if points < 2:
            raise InstrumentCommandError("Sweep points must be at least 2.")
        self.write(f":SENS1:SWE:POIN {int(points)}", check_error=True)

    def get_start_frequency(self) -> float:
        return float(self.query(":SENS1:FREQ:STAR?"))

    def get_stop_frequency(self) -> float:
        return float(self.query(":SENS1:FREQ:STOP?"))

    def get_sweep_points(self) -> int:
        return int(float(self.query(":SENS1:SWE:POIN?")))

    def trigger_single_sweep(self) -> None:
        self._ensure_connected()
        self._emit("Connection", "Single sweep started")
        self.write(":TRIG:SEQ:SOUR BUS")
        self.write(":INIT1:CONT OFF")
        self.write(":INIT1")
        self.write("*TRG")
        self._emit("Connection", "Waiting for operation complete")
        response = self.query("*OPC?")
        if response.strip() not in {"1", "+1"}:
            raise InstrumentCommandError(f"Unexpected *OPC? response: {response}")
        self._emit("Connection", "Sweep complete")
        self._raise_if_system_error()

    def configure_v02_measurement(
        self,
        start_hz: float,
        stop_hz: float,
        points: int,
        marker_hz: Sequence[float],
        traces: Sequence[Any] | None = None,
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        self._validate_frequency(start_hz, "Start frequency")
        self._validate_frequency(stop_hz, "Stop frequency")
        if start_hz >= stop_hz:
            raise InstrumentCommandError("Start frequency must be less than stop frequency.")
        if points < 2:
            raise InstrumentCommandError("Sweep points must be at least 2.")
        if not marker_hz:
            raise InstrumentCommandError("At least one marker frequency is required.")
        if len(marker_hz) > 10:
            raise InstrumentCommandError("E5071C supports up to 10 markers.")
        for marker in marker_hz:
            if marker < start_hz or marker > stop_hz:
                raise InstrumentCommandError("Marker frequency must be inside sweep span.")

        trace_specs = list(traces or self._default_v02_traces())
        if not trace_specs:
            raise InstrumentCommandError("At least one trace is required.")

        self.set_start_frequency(start_hz)
        self.set_stop_frequency(stop_hz)
        self.set_sweep_points(points)
        self._control_write(f":CALC{channel}:PAR:COUN {len(trace_specs)}")
        self._control_write(":DISP:SPL D1")
        self._control_write(f":DISP:WIND{channel}:SPL D1")

        for index, trace in enumerate(trace_specs, 1):
            measurement = str(getattr(trace, "measurement", "")).upper()
            display_format = str(getattr(trace, "display_format", "")).upper()
            self._ensure_measurement_parameter(measurement)
            self._ensure_display_format(display_format)
            self._control_write(f":CALC{channel}:PAR{index}:DEF {measurement}")
            self._control_write(f":CALC{channel}:PAR{index}:SEL")
            self._control_write(f":CALC{channel}:FORM {display_format}")
            if self.mock:
                self._mock_trace_measurements[index] = measurement
            for marker_index, marker in enumerate(marker_hz, 1):
                self._control_write(f":CALC{channel}:TRAC{index}:MARK{marker_index}:ACT")
                self._control_write(
                    f":CALC{channel}:TRAC{index}:MARK{marker_index}:X {marker:.12g}"
                )

        self._control_write(":DISP:TABL OFF")
        self._raise_if_system_error()

    def read_v02_marker_results(
        self,
        marker_hz: Sequence[float],
        traces: Sequence[Any] | None = None,
        channel: int = 1,
    ) -> list[MarkerResult]:
        self._ensure_channel(channel)
        trace_specs = list(traces or self._default_v02_traces())
        results: list[MarkerResult] = []
        for trace_index, trace in enumerate(trace_specs, 1):
            measurement = str(getattr(trace, "measurement", "")).upper()
            self._ensure_measurement_parameter(measurement)
            for marker_index, frequency in enumerate(marker_hz, 1):
                response = self._query_raw(
                    f":CALC{channel}:TRAC{trace_index}:MARK{marker_index}:Y?"
                )
                primary, secondary = self._parse_pair(response)
                results.append(
                    MarkerResult(
                        trace=measurement,
                        trace_number=trace_index,
                        marker=marker_index,
                        frequency_hz=float(frequency),
                        primary=primary,
                        secondary=secondary,
                    )
                )
        return results

    def display_traces_data_and_memory(
        self,
        traces: Sequence[int] = (1, 2, 3),
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        trace_numbers = self._ensure_traces(traces)
        for trace in trace_numbers:
            self._control_write(f":DISP:WIND{channel}:TRAC{trace}:STAT ON")
            self._control_write(f":DISP:WIND{channel}:TRAC{trace}:MEM ON")
        self._raise_if_system_error()

    def copy_traces_data_to_memory(
        self,
        traces: Sequence[int] = (1, 2, 3),
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        trace_numbers = self._ensure_traces(traces)
        for trace in trace_numbers:
            self._control_write(f":CALC{channel}:PAR{trace}:SEL")
            self._control_write(f":CALC{channel}:MATH:MEM")
        self._raise_if_system_error()

    def capture_screen_image(
        self,
        image_format: str = "PNG",
        vna_path: str | None = None,
        keep_vna_copy: bool = False,
    ) -> bytes:
        image_format = self._safe_image_format(image_format)
        image_path = self._safe_vna_image_path(
            vna_path or self._temporary_vna_image_path(image_format)
        )
        self.save_screen_image_on_vna(image_path)
        image = self.transfer_file_from_vna(image_path)
        if not keep_vna_copy:
            self._delete_vna_file_best_effort(image_path)
        return image

    def save_screen_image_on_vna(self, vna_path: str) -> None:
        image_path = self._safe_vna_image_path(vna_path)
        self._ensure_vna_parent_directory(image_path)
        self._control_write(f':MMEM:STOR:IMAG "{image_path}"')
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def transfer_file_from_vna(self, vna_path: str) -> bytes:
        self._ensure_connected()
        image_path = self._safe_vna_image_path(vna_path)
        return self._query_binary_block(f':MMEM:TRAN? "{image_path}"')

    def delete_vna_file(self, vna_path: str) -> None:
        image_path = self._safe_vna_image_path(vna_path)
        self._control_write(f':MMEM:DEL "{image_path}"')
        self._raise_if_system_error()

    def _delete_vna_file_best_effort(self, vna_path: str) -> None:
        try:
            self.delete_vna_file(vna_path)
        except InstrumentError as exc:
            self._emit("Error", f"Temporary VNA image cleanup failed: {exc}")

    def start_two_port_solt_calibration(
        self,
        cal_kit: str = "85032F",
        ports: tuple[int, int] = (1, 2),
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        self._ensure_ports(ports, expected_count=2)
        safe_cal_kit = self._safe_label(cal_kit, "Cal kit")
        self._control_write(f':SENS{channel}:CORR:COLL:CKIT "{safe_cal_kit}"')
        self._control_write(f":SENS{channel}:CORR:COLL:METH:SOLT2 {ports[0]},{ports[1]}")
        self._raise_if_system_error()

    def acquire_calibration_standard(
        self,
        standard: str,
        ports: tuple[int, ...],
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        normalized = self._normalize_standard(standard)
        if normalized in {"OPEN", "SHOR", "LOAD"}:
            self._ensure_ports(ports, expected_count=1)
            self._control_write(f":SENS{channel}:CORR:COLL:{normalized} {ports[0]}")
        elif normalized == "THRU":
            self._ensure_ports(ports, expected_count=2)
            self._control_write(f":SENS{channel}:CORR:COLL:THRU {ports[0]},{ports[1]}")
        else:
            raise InstrumentCommandError(f"Unsupported calibration standard: {standard}")
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def save_calibration(self, channel: int = 1) -> None:
        self._ensure_channel(channel)
        self._control_write(f":SENS{channel}:CORR:COLL:SAVE")
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def cancel_calibration(self, channel: int = 1) -> None:
        self._ensure_channel(channel)
        self._control_write(f":SENS{channel}:CORR:COLL:CLE")
        self._wait_for_operation_complete()

    def list_ecal_modules(self) -> list[str]:
        response = self._query_raw(":SYST:COMM:ECAL:CAT?")
        return [item.strip().strip('"') for item in response.split(",") if item.strip()]

    def select_ecal_module(self, ecal_id: str) -> None:
        safe_id = self._safe_ecal_id(ecal_id)
        self._control_write(f':SYST:COMM:ECAL:DEF "{safe_id}"')
        self._raise_if_system_error()

    def set_ecal_auto_orientation(self, enabled: bool, channel: int = 1) -> None:
        self._ensure_channel(channel)
        self._control_write(f":SENS{channel}:CORR:COLL:ECAL:ORI {self._bool_word(enabled)}")
        self._raise_if_system_error()

    def perform_two_port_ecal(
        self,
        ports: tuple[int, int] = (1, 2),
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        self._ensure_ports(ports, expected_count=2)
        self._control_write(f":SENS{channel}:CORR:COLL:ECAL:SOLT2 {ports[0]},{ports[1]}")
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def perform_ecal_confidence_check(self, channel: int = 1) -> None:
        self._ensure_channel(channel)
        self._control_write(f":SENS{channel}:CORR:COLL:ECAL:CCH")
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def configure_auto_port_extension(
        self,
        port: int,
        include_loss: bool = True,
        adjust_mismatch: bool = False,
        method: str = "CSPN",
        channel: int = 1,
    ) -> None:
        self.configure_auto_port_extension_ports(
            ports=(port,),
            include_loss=include_loss,
            adjust_mismatch=adjust_mismatch,
            method=method,
            channel=channel,
        )

    def configure_auto_port_extension_ports(
        self,
        ports: Sequence[int],
        include_loss: bool = True,
        adjust_mismatch: bool = False,
        method: str = "CSPN",
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        selected_ports = self._ensure_auto_port_extension_ports(ports)
        method = method.upper()
        if method not in {"CSPN", "AMKR", "USPN"}:
            raise InstrumentCommandError("Auto port extension method must be CSPN, AMKR, or USPN.")
        self._control_write(f":SENS{channel}:CORR:EXT ON")
        self._control_write(f":SENS{channel}:CORR:EXT:AUTO:CONF {method}")
        self._select_auto_port_extension_ports(selected_ports, channel)
        self._control_write(f":SENS{channel}:CORR:EXT:AUTO:LOSS {self._bool_word(include_loss)}")
        self._control_write(f":SENS{channel}:CORR:EXT:AUTO:DCOF {self._bool_word(adjust_mismatch)}")
        self._raise_if_system_error()

    def measure_auto_port_extension(
        self,
        port: int,
        standard: str = "OPEN",
        channel: int = 1,
    ) -> None:
        self.measure_auto_port_extension_ports(ports=(port,), standard=standard, channel=channel)

    def measure_auto_port_extension_ports(
        self,
        ports: Sequence[int],
        standard: str = "OPEN",
        channel: int = 1,
    ) -> None:
        self._ensure_channel(channel)
        selected_ports = self._ensure_auto_port_extension_ports(ports)
        normalized = self._normalize_standard(standard)
        if normalized not in {"OPEN", "SHOR"}:
            raise InstrumentCommandError("Auto port extension standard must be OPEN or SHOR.")
        self._select_auto_port_extension_ports(selected_ports, channel)
        self._control_write(f":SENS{channel}:CORR:EXT:AUTO:MEAS {normalized}")
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def _select_auto_port_extension_ports(self, ports: tuple[int, ...], channel: int) -> None:
        for selectable_port in (1, 2):
            self._control_write(f":SENS{channel}:CORR:EXT:AUTO:PORT{selectable_port} OFF")
        for port in ports:
            self._control_write(f":SENS{channel}:CORR:EXT:AUTO:PORT{port} ON")

    def get_port_extension_result(self, port: int, channel: int = 1) -> PortExtensionResult:
        self._ensure_channel(channel)
        self._ensure_port(port)
        return PortExtensionResult(
            port=port,
            delay_s=float(self._query_raw(f":SENS{channel}:CORR:EXT:PORT{port}:TIME?")),
            loss1_db=float(self._query_raw(f":SENS{channel}:CORR:EXT:PORT{port}:LOSS1?")),
            loss2_db=float(self._query_raw(f":SENS{channel}:CORR:EXT:PORT{port}:LOSS2?")),
            freq1_hz=float(self._query_raw(f":SENS{channel}:CORR:EXT:PORT{port}:FREQ1?")),
            freq2_hz=float(self._query_raw(f":SENS{channel}:CORR:EXT:PORT{port}:FREQ2?")),
        )

    def get_port_extension_results(
        self, ports: Sequence[int], channel: int = 1
    ) -> list[PortExtensionResult]:
        selected_ports = self._ensure_auto_port_extension_ports(ports)
        return [
            self.get_port_extension_result(port=port, channel=channel) for port in selected_ports
        ]

    def save_state(self, name: str, save_type: str = "CDST") -> None:
        state_path = self._safe_state_path(name)
        save_type = save_type.upper()
        if save_type not in {"STAT", "CST", "DST", "CDST"}:
            raise InstrumentCommandError("Save type must be STAT, CST, DST, or CDST.")
        self._control_write(f":MMEM:STOR:STYP {save_type}")
        self._control_write(f':MMEM:STOR "{state_path}"')
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def recall_state(self, name: str) -> None:
        state_path = self._safe_state_path(name)
        self._control_write(f':MMEM:LOAD "{state_path}"')
        self._wait_for_operation_complete()
        self._raise_if_system_error()

    def _emit(self, kind: str, message: str) -> None:
        if self.log_callback is not None:
            self.log_callback(kind, message)

    def _configure_session_terminations(self) -> None:
        if self._session is None:
            return
        for attr in ("write_termination", "read_termination"):
            with suppress(Exception):
                setattr(self._session, attr, "\n")

    def _connection_resource_candidates(self) -> tuple[str, ...]:
        candidates: list[str] = []
        for resource in (
            self.resource,
            self.build_resource(self.ip_address),
            self.build_vxi11_resource(self.ip_address),
        ):
            resource = resource.strip()
            if resource and resource not in candidates:
                candidates.append(resource)
        return tuple(candidates)

    def _connect_resource(self, pyvisa_module: Any, resource: str) -> InstrumentIdentity:
        self.resource = resource
        self._emit("Connection", f"Opening VISA resource: {resource}")
        try:
            self._resource_manager = pyvisa_module.ResourceManager("@py")
            self._session = self._resource_manager.open_resource(resource)
            self._session.timeout = self.timeout_ms
            self._configure_session_terminations()
            self._connected = True
            self._emit("Connection", "VISA resource opened")

            idn = self._query_during_connect("*IDN?")
            self.identity = InstrumentIdentity.from_idn(idn)
            self.last_system_error = self._query_during_connect("SYST:ERR?")
            if not self.system_error_is_clear(self.last_system_error):
                self._emit("Error", f"SYST:ERR returned {self.last_system_error}")
            self._emit("Connection", "Instrument connected successfully")
            return self.identity
        except InstrumentError:
            raise
        except Exception as exc:
            raise self._map_exception(exc, opening=True) from exc

    def _query_during_connect(self, command: str) -> str:
        self._emit("TX", command)
        if self._session is None:
            raise InstrumentConnectionError("VISA session is not open.")
        try:
            response = str(self._session.query(command)).strip()
        except Exception as exc:
            raise self._map_exception(exc, opening=True) from exc
        self._emit("RX", response)
        return response

    def _format_connection_failures(self, failures: list[tuple[str, InstrumentError]]) -> str:
        if len(failures) == 1:
            return str(failures[0][1])
        lines = ["Could not connect to E5071C using the available LAN VISA resources."]
        lines.extend(f"- {resource}: {error}" for resource, error in failures)
        lines.append(
            "Check the IP address, E5071C LAN remote-control setting, and firewall. "
            "For SOCKET mode, the analyzer must answer SCPI on TCP port 5025; "
            "for inst0::INSTR mode, enable the instrument LAN/VXI-11 service."
        )
        return "\n".join(lines)

    def _close_session(self) -> None:
        for obj_name in ("_session", "_resource_manager"):
            obj = getattr(self, obj_name)
            if obj is None:
                continue
            with suppress(Exception):
                obj.close()
            setattr(self, obj_name, None)

    def _write_raw(self, command: str) -> None:
        self._emit("TX", command)
        try:
            if self.mock:
                self._mock_write(command)
            else:
                if self._session is None:
                    raise InstrumentConnectionError("VISA session is not open.")
                self._session.write(command)
        except InstrumentError:
            raise
        except Exception as exc:
            error = self._map_exception(exc)
            self._handle_io_error(error)
            raise error from exc

    def _query_raw(self, command: str) -> str:
        self._emit("TX", command)
        try:
            if self.mock:
                response = self._mock_query(command)
            else:
                if self._session is None:
                    raise InstrumentConnectionError("VISA session is not open.")
                response = str(self._session.query(command))
            response = response.strip()
            self._emit("RX", response)
            return response
        except InstrumentError:
            raise
        except Exception as exc:
            error = self._map_exception(exc)
            self._handle_io_error(error)
            raise error from exc

    def _query_binary_block(self, command: str) -> bytes:
        self._emit("TX", command)
        try:
            if self.mock:
                data = self._mock_query_binary_block(command)
            else:
                if self._session is None:
                    raise InstrumentConnectionError("VISA session is not open.")
                self._session.write(command)
                data = self._read_ieee_binary_block_response()
            self._emit("RX", f"<{len(data)} bytes>")
            return data
        except InstrumentError:
            raise
        except Exception as exc:
            error = self._map_exception(exc)
            self._handle_io_error(error)
            raise error from exc

    def _control_write(self, command: str) -> None:
        self._ensure_connected()
        self._write_raw(command)

    def _wait_for_operation_complete(self) -> None:
        response = self._query_raw("*OPC?")
        if response.strip() not in {"1", "+1"}:
            raise InstrumentCommandError(f"Unexpected *OPC? response: {response}")

    def _read_ieee_binary_block_response(self) -> bytes:
        prefix = self._read_session_bytes(2)
        if len(prefix) != 2 or prefix[:1] != b"#":
            raise InstrumentCommandError("Expected IEEE binary block response.")
        digit_count_text = prefix[1:2].decode("ascii", errors="strict")
        if not digit_count_text.isdigit():
            raise InstrumentCommandError("Invalid binary block header.")
        digit_count = int(digit_count_text)
        if digit_count == 0:
            raise InstrumentCommandError("Indefinite binary blocks are not supported.")
        length_text = self._read_session_bytes(digit_count).decode("ascii", errors="strict")
        if not length_text.isdigit():
            raise InstrumentCommandError("Invalid binary block length.")
        data = self._read_session_bytes(int(length_text))
        self._drain_binary_terminator()
        return data

    def _read_session_bytes(self, count: int) -> bytes:
        if self._session is None:
            raise InstrumentConnectionError("VISA session is not open.")
        data = bytearray()
        while len(data) < count:
            remaining = count - len(data)
            if hasattr(self._session, "read_bytes"):
                chunk = self._session.read_bytes(remaining)
            else:
                try:
                    chunk = self._session.read_raw(remaining)
                except TypeError:
                    chunk = self._session.read_raw()
            chunk = bytes(chunk)
            if not chunk:
                raise InstrumentConnectionError("Instrument returned an incomplete binary block.")
            data.extend(chunk[:remaining])
        return bytes(data)

    def _drain_binary_terminator(self) -> None:
        if self._session is None:
            return
        original_timeout = getattr(self._session, "timeout", None)
        try:
            if original_timeout is not None:
                with suppress(Exception):
                    self._session.timeout = min(int(original_timeout), 200)
            terminator = self._read_session_bytes(1)
            if terminator == b"\r":
                self._read_session_bytes(1)
        except Exception:
            pass
        finally:
            if original_timeout is not None:
                with suppress(Exception):
                    self._session.timeout = original_timeout

    def _handle_io_error(self, error: InstrumentError) -> None:
        self._emit("Error", str(error))
        if isinstance(error, InstrumentConnectionError):
            self._connected = False
            self._emit("Connection", "Connection Lost")

    def _map_exception(self, exc: Exception, opening: bool = False) -> InstrumentError:
        text = str(exc)
        upper = text.upper()

        if "VI_ERROR_RSRC_NFOUND" in upper or "RESOURCE NOT FOUND" in upper:
            return InstrumentConnectionError(f"VISA resource not found: {self.resource}")
        if "VI_ERROR_TMO" in upper or "TIMEOUT" in upper or "TIMED OUT" in upper:
            return InstrumentTimeoutError(
                f"Instrument timeout after {self.timeout_ms} ms on {self.resource}."
            )
        if "CONNECTION REFUSED" in upper:
            return InstrumentConnectionError(f"Connection refused by {self.resource}.")
        if "NO ROUTE" in upper or "UNREACHABLE" in upper or "BROKEN PIPE" in upper:
            return InstrumentConnectionError(f"LAN disconnected or unreachable: {self.resource}.")
        if opening:
            return InstrumentConnectionError(
                f"Could not open VISA resource {self.resource}: {text}"
            )
        return InstrumentConnectionError(f"Instrument communication failed: {text}")

    def _raise_if_system_error(self) -> None:
        errors: list[str] = []
        for _ in range(32):
            response = self.query_error()
            if self.system_error_is_clear(response):
                if errors:
                    raise InstrumentCommandError(
                        "Instrument reported SCPI error: " + "; ".join(errors)
                    )
                return
            errors.append(response)
        raise InstrumentCommandError(
            "Instrument SCPI error queue did not clear: " + "; ".join(errors)
        )

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise InstrumentConnectionError("Instrument disconnected.")

    def _ensure_safe_scpi(self, command: str) -> None:
        for segment in self._segments(command):
            if "?" in segment:
                continue
            if not self._is_allowed_write_segment(segment):
                raise InstrumentSafetyError(
                    "Blocked by V0.1 safety policy. Only Start Frequency, Stop "
                    "Frequency, Sweep Points, and Single Sweep writes are allowed."
                )

    def _is_allowed_write_segment(self, segment: str) -> bool:
        header = self._header(segment)
        parameter = self._parameter(segment)
        parameter_upper = parameter.upper()

        if header in self._START_HEADERS or header in self._STOP_HEADERS:
            return self._is_number(parameter)
        if header in self._POINT_HEADERS:
            return parameter.isdigit() and int(parameter) >= 2
        if header in self._INIT_CONT_HEADERS:
            return parameter_upper in {"OFF", "0"}
        if header in self._INIT_SINGLE_HEADERS:
            return parameter == ""
        if header in self._TRIGGER_SOURCE_HEADERS:
            return parameter_upper == "BUS"
        if header == "*TRG":
            return parameter == ""
        return False

    def _mock_query(self, command: str) -> str:
        response = ""
        for segment in self._segments(command):
            if "?" in segment:
                response = self._mock_single_query(segment)
            else:
                self._mock_write(segment)
        return response

    def _mock_single_query(self, segment: str) -> str:
        header = self._header(segment).replace("?", "")
        if header == "*IDN":
            return self.MOCK_IDN
        if header in {"SYST:ERR", "SYSTEM:ERROR"}:
            response = self._mock_system_error
            self._mock_system_error = '+0,"No error"'
            return response
        if header in self._START_HEADERS:
            return f"{self._mock_start_hz:.12g}"
        if header in self._STOP_HEADERS:
            return f"{self._mock_stop_hz:.12g}"
        if header in self._POINT_HEADERS:
            return str(self._mock_points)
        if header == "*OPC":
            return "1"
        if header == "SYST:COMM:ECAL:CAT":
            return ",".join(f'"{module}"' for module in self._mock_ecal_modules)
        if header == "SYST:COMM:ECAL:DEF":
            return self._mock_selected_ecal
        if header == "MMEM:CAT":
            directory = self._normalize_vna_directory_path(
                self._parameter(segment).strip().strip('"')
            )
            children: list[str] = []
            prefix = f"{directory}\\" if directory else ""
            for candidate in self._mock_vna_directories:
                if candidate == directory or not candidate.startswith(prefix):
                    continue
                remainder = candidate[len(prefix) :]
                if remainder and "\\" not in remainder:
                    children.append(remainder)
            entries = ",".join(f'"{name}",,0' for name in sorted(children))
            return f"0,100000000,{entries}" if entries else "0,100000000"
        marker_match = re.fullmatch(r"CALC\d+:TRAC(\d+):MARK(\d+):Y", header)
        if marker_match:
            trace = int(marker_match.group(1))
            marker = int(marker_match.group(2))
            measurement = self._mock_trace_measurements.get(trace, "")
            if measurement in {"S11", "S22"}:
                return "50,0"
            if measurement == "S21":
                return "-1.0,0"
            return f"{self._mock_markers.get((trace, marker), 0.0):.12g},0"
        port_ext_match = re.fullmatch(
            r"SENS\d+:CORR:EXT:PORT([1-4]):(TIME|LOSS[12]|FREQ[12])", header
        )
        if port_ext_match:
            result = self._mock_port_extension[int(port_ext_match.group(1))]
            field_name = port_ext_match.group(2)
            if field_name == "TIME":
                return f"{result.delay_s:.12g}"
            if field_name == "LOSS1":
                return f"{result.loss1_db:.12g}"
            if field_name == "LOSS2":
                return f"{result.loss2_db:.12g}"
            if field_name == "FREQ1":
                return f"{result.freq1_hz:.12g}"
            if field_name == "FREQ2":
                return f"{result.freq2_hz:.12g}"

        self._mock_system_error = '-113,"Undefined header"'
        raise InstrumentCommandError(f"Invalid SCPI for mock E5071C: {segment}")

    def _mock_query_binary_block(self, command: str) -> bytes:
        header = self._header(command).replace("?", "")
        if header == "MMEM:TRAN":
            if self._mock_screen_capture_format == "BMP":
                return b"BMmock-smithpilot-screen-capture"
            return b"\x89PNG\r\n\x1a\nmock-smithpilot-screen-capture"
        self._mock_system_error = '-113,"Undefined header"'
        raise InstrumentCommandError(f"Invalid binary query for mock E5071C: {command}")

    def _mock_write(self, command: str) -> None:
        for segment in self._segments(command):
            header = self._header(segment)
            parameter = self._parameter(segment)

            if header in self._START_HEADERS:
                self._mock_start_hz = float(parameter)
            elif header in self._STOP_HEADERS:
                self._mock_stop_hz = float(parameter)
            elif header in self._POINT_HEADERS:
                self._mock_points = int(parameter)
            elif (
                header in self._INIT_CONT_HEADERS
                or header in self._INIT_SINGLE_HEADERS
                or header in self._TRIGGER_SOURCE_HEADERS
                or header == "*TRG"
            ):
                pass
            elif self._mock_accepts_v02_write(header, parameter):
                self._mock_apply_v02_write(header, parameter)
            else:
                self._mock_system_error = '-113,"Undefined header"'
                raise InstrumentCommandError(f"Invalid SCPI for mock E5071C: {segment}")

    def _mock_accepts_v02_write(self, header: str, parameter: str) -> bool:
        patterns = (
            r"CALC\d+:PAR:COUN",
            r"DISP:SPL",
            r"DISP:WIND\d+:SPL",
            r"CALC\d+:PAR\d+:DEF",
            r"CALC\d+:PAR\d+:SEL",
            r"CALC\d+:FORM",
            r"CALC\d+:TRAC\d+:MARK\d+:ACT",
            r"CALC\d+:TRAC\d+:MARK\d+:X",
            r"DISP:WIND\d+:TRAC\d+:STAT",
            r"DISP:WIND\d+:TRAC\d+:MEM",
            r"CALC\d+:MATH:MEM",
            r"DISP:TABL",
            r"DISP:TABL:TYPE",
            r"SENS\d+:CORR:COLL:CKIT",
            r"SENS\d+:CORR:COLL:METH:SOLT2",
            r"SENS\d+:CORR:COLL:(OPEN|SHOR|LOAD|THRU|SAVE|CLE)",
            r"SENS\d+:CORR:COLL:ECAL:ORI",
            r"SENS\d+:CORR:COLL:ECAL:SOLT2",
            r"SENS\d+:CORR:COLL:ECAL:CCH",
            r"SYST:COMM:ECAL:DEF",
            r"SENS\d+:CORR:EXT",
            r"SENS\d+:CORR:EXT:AUTO:CONF",
            r"SENS\d+:CORR:EXT:AUTO:PORT[1-4]",
            r"SENS\d+:CORR:EXT:AUTO:LOSS",
            r"SENS\d+:CORR:EXT:AUTO:DCOF",
            r"SENS\d+:CORR:EXT:AUTO:MEAS",
            r"MMEM:STOR:IMAG",
            r"MMEM:MDIR",
            r"MMEM:DEL",
            r"MMEM:STOR:STYP",
            r"MMEM:STOR",
            r"MMEM:LOAD",
        )
        return any(re.fullmatch(pattern, header) for pattern in patterns)

    def _mock_apply_v02_write(self, header: str, parameter: str) -> None:
        trace_def_match = re.fullmatch(r"CALC\d+:PAR(\d+):DEF", header)
        if trace_def_match:
            self._mock_trace_measurements[int(trace_def_match.group(1))] = parameter.upper()
            return
        marker_match = re.fullmatch(r"CALC\d+:TRAC(\d+):MARK(\d+):X", header)
        if marker_match:
            self._mock_markers[(int(marker_match.group(1)), int(marker_match.group(2)))] = float(
                parameter
            )
            return
        if header == "SYST:COMM:ECAL:DEF":
            self._mock_selected_ecal = parameter.strip().strip('"')
            return
        if header == "MMEM:STOR:IMAG":
            suffix = PureWindowsPath(parameter.strip().strip('"')).suffix.lstrip(".")
            self._mock_screen_capture_format = self._safe_image_format(suffix)
            return
        if header == "MMEM:MDIR":
            directory = self._normalize_vna_directory_path(parameter.strip().strip('"'))
            self._mock_vna_directories.add(directory)
            return
        ext_port_match = re.fullmatch(r"SENS\d+:CORR:EXT:AUTO:PORT([1-4])", header)
        if ext_port_match:
            port = int(ext_port_match.group(1))
            parameter_upper = parameter.upper()
            if parameter_upper in {"ON", "1"}:
                self._mock_auto_port_extension_ports.add(port)
                return
            if parameter_upper in {"OFF", "0"}:
                self._mock_auto_port_extension_ports.discard(port)
                return
            self._mock_system_error = '-222,"Data out of range"'
            raise InstrumentCommandError(f"Invalid Auto Port Extension port state: {parameter}")
        ext_measure_match = re.fullmatch(r"SENS\d+:CORR:EXT:AUTO:MEAS", header)
        if ext_measure_match:
            for port in sorted(self._mock_auto_port_extension_ports):
                self._mock_port_extension[port] = PortExtensionResult(
                    port=port,
                    delay_s=1.25e-10 * port,
                    loss1_db=0.1 * port,
                    loss2_db=0.2 * port,
                    freq1_hz=self._mock_start_hz,
                    freq2_hz=self._mock_stop_hz,
                )

    @staticmethod
    def _clean_command(command: str) -> str:
        command = command.strip()
        if not command:
            raise InstrumentCommandError("SCPI command is empty.")
        return command

    @staticmethod
    def _segments(command: str) -> list[str]:
        return [segment.strip() for segment in command.split(";") if segment.strip()]

    @staticmethod
    def _header(segment: str) -> str:
        header = segment.strip().split(maxsplit=1)[0].strip()
        if header.startswith(":"):
            header = header[1:]
        return header.upper()

    @staticmethod
    def _parameter(segment: str) -> str:
        parts = segment.strip().split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    @staticmethod
    def _is_number(value: str) -> bool:
        return bool(re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([Ee][+-]?\d+)?", value.strip()))

    @staticmethod
    def _validate_frequency(freq_hz: float, label: str) -> None:
        if freq_hz <= 0:
            raise InstrumentCommandError(f"{label} must be greater than 0 Hz.")

    @staticmethod
    def _default_v02_traces() -> tuple[Any, ...]:
        class _Trace:
            def __init__(self, measurement: str, display_format: str) -> None:
                self.measurement = measurement
                self.display_format = display_format

        return (_Trace("S11", "SMIT"), _Trace("S22", "SMIT"), _Trace("S21", "MLOG"))

    @staticmethod
    def _ensure_channel(channel: int) -> None:
        if channel < 1 or channel > 160:
            raise InstrumentCommandError("Channel must be between 1 and 160.")

    @staticmethod
    def _ensure_port(port: int) -> None:
        if port < 1 or port > 4:
            raise InstrumentCommandError("Port must be between 1 and 4.")

    @classmethod
    def _ensure_ports(cls, ports: tuple[int, ...], expected_count: int) -> None:
        if len(ports) != expected_count:
            raise InstrumentCommandError(f"Expected {expected_count} port value(s).")
        for port in ports:
            cls._ensure_port(port)
        if len(set(ports)) != len(ports):
            raise InstrumentCommandError("Port values must be unique.")

    @staticmethod
    def _ensure_auto_port_extension_ports(ports: Sequence[int]) -> tuple[int, ...]:
        selected_ports = tuple(ports)
        if not selected_ports:
            raise InstrumentCommandError("Select at least one Auto Port Extension port.")
        if len(set(selected_ports)) != len(selected_ports):
            raise InstrumentCommandError("Auto Port Extension port values must be unique.")
        for port in selected_ports:
            if isinstance(port, bool) or port not in {1, 2}:
                raise InstrumentCommandError(
                    "Auto Port Extension supports Port 1, Port 2, or both."
                )
        return selected_ports

    @staticmethod
    def _ensure_traces(traces: Sequence[int]) -> tuple[int, ...]:
        trace_numbers = tuple(traces)
        if not trace_numbers:
            raise InstrumentCommandError("Select at least one trace.")
        if len(set(trace_numbers)) != len(trace_numbers):
            raise InstrumentCommandError("Trace values must be unique.")
        for trace in trace_numbers:
            if isinstance(trace, bool) or trace < 1 or trace > 16:
                raise InstrumentCommandError("Trace must be between 1 and 16.")
        return trace_numbers

    @staticmethod
    def _ensure_measurement_parameter(measurement: str) -> None:
        if measurement not in {"S11", "S12", "S21", "S22"}:
            raise InstrumentCommandError(f"Unsupported measurement parameter: {measurement}")

    @staticmethod
    def _ensure_display_format(display_format: str) -> None:
        if display_format not in {"SMIT", "SMITH", "MLOG", "SWR", "PHAS", "POL"}:
            raise InstrumentCommandError(f"Unsupported display format: {display_format}")

    @staticmethod
    def _normalize_standard(standard: str) -> str:
        normalized = standard.strip().upper()
        if normalized == "SHORT":
            return "SHOR"
        return normalized

    @staticmethod
    def _bool_word(value: bool) -> str:
        return "ON" if value else "OFF"

    @staticmethod
    def _parse_pair(response: str) -> tuple[float, float]:
        parts = [part.strip() for part in response.split(",")]
        if len(parts) < 2:
            raise InstrumentCommandError(f"Expected numeric pair, got: {response}")
        return float(parts[0]), float(parts[1])

    @staticmethod
    def _parse_ieee_binary_block(raw: bytes) -> bytes:
        if not raw.startswith(b"#"):
            return raw.rstrip(b"\r\n")
        if len(raw) < 2:
            raise InstrumentCommandError("Invalid binary block response.")
        digit_count = int(chr(raw[1]))
        if digit_count == 0:
            return raw[2:].rstrip(b"\r\n")
        header_end = 2 + digit_count
        if len(raw) < header_end:
            raise InstrumentCommandError("Incomplete binary block header.")
        data_length = int(raw[2:header_end].decode("ascii"))
        data_end = header_end + data_length
        if len(raw) < data_end:
            raise InstrumentCommandError("Incomplete binary block data.")
        return raw[header_end:data_end]

    @staticmethod
    def _safe_image_format(value: str) -> str:
        image_format = value.strip().upper()
        if image_format not in {"PNG", "BMP"}:
            raise InstrumentCommandError("Screen capture format must be PNG or BMP.")
        return image_format

    @staticmethod
    def _temporary_vna_image_path(image_format: str) -> str:
        return f"D:SmithPilotCaptureTemp.{image_format.lower()}"

    def _ensure_vna_parent_directory(self, vna_path: str) -> None:
        parent = PureWindowsPath(vna_path).parent
        if not parent.root:
            return

        current = PureWindowsPath(parent.anchor)
        for part in parent.parts[1:]:
            names = self._list_vna_directory_names(str(current))
            candidate = current / part
            if part.casefold() not in {name.casefold() for name in names}:
                directory = self._safe_vna_directory_path(str(candidate))
                self._control_write(f':MMEM:MDIR "{directory}"')
                self._raise_if_system_error()
            current = candidate

    def _list_vna_directory_names(self, directory: str) -> tuple[str, ...]:
        safe_directory = self._safe_vna_directory_path(directory)
        response = self._query_raw(f':MMEM:CAT? "{safe_directory}"')
        self._raise_if_system_error()
        return self._parse_vna_catalog_names(response)

    @staticmethod
    def _parse_vna_catalog_names(response: str) -> tuple[str, ...]:
        fields = next(csv.reader([response.strip()]))
        if len(fields) == 1 and "," in fields[0]:
            fields = next(csv.reader([fields[0]]))
        if len(fields) < 2:
            raise InstrumentCommandError(f"Invalid VNA directory catalog: {response}")
        return tuple(
            field.strip().rstrip("\\/") for field in fields[2::3] if field.strip().rstrip("\\/")
        )

    @staticmethod
    def _normalize_vna_directory_path(value: str) -> str:
        return str(PureWindowsPath(value)).rstrip("\\/").casefold()

    @staticmethod
    def _safe_vna_directory_path(value: str) -> str:
        text = value.strip()
        if not text or len(text) > 254:
            raise InstrumentCommandError("VNA directory path must be 1-254 characters.")
        if '"' in text or ";" in text or "\r" in text or "\n" in text:
            raise InstrumentCommandError("VNA directory path contains unsupported characters.")
        if not re.fullmatch(r"[A-Za-z0-9_.:/\\ -]+", text):
            raise InstrumentCommandError("VNA directory path contains unsupported characters.")
        if any(part == ".." for part in re.split(r"[\\/]", text)):
            raise InstrumentCommandError("VNA directory path cannot contain '..' path segments.")
        return text

    @staticmethod
    def _safe_vna_image_path(value: str) -> str:
        text = value.strip()
        if not text or len(text) > 254:
            raise InstrumentCommandError("VNA image path must be 1-254 characters.")
        if '"' in text or ";" in text or "\r" in text or "\n" in text:
            raise InstrumentCommandError("VNA image path contains unsupported characters.")
        if not re.fullmatch(r"[A-Za-z0-9_.:/\\ -]+", text):
            raise InstrumentCommandError("VNA image path contains unsupported characters.")
        if any(part == ".." for part in re.split(r"[\\/]", text)):
            raise InstrumentCommandError("VNA image path cannot contain '..' path segments.")
        if PureWindowsPath(text).suffix.lower() not in {".png", ".bmp"}:
            raise InstrumentCommandError("VNA image path must end with .png or .bmp.")
        return text

    @staticmethod
    def _safe_label(value: str, label: str) -> str:
        text = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_. -]{1,64}", text):
            raise InstrumentCommandError(f"{label} contains unsupported characters.")
        return text

    @staticmethod
    def _safe_ecal_id(value: str) -> str:
        text = value.strip().strip('"')
        if not re.fullmatch(r"[A-Za-z0-9_. -]{1,80}", text):
            raise InstrumentCommandError("ECal ID contains unsupported characters.")
        return text

    @classmethod
    def _safe_state_path(cls, name: str) -> str:
        text = cls._safe_label(name, "State name").replace(" ", "_")
        filename = PureWindowsPath(text).name
        if not filename.lower().endswith(".sta"):
            filename = f"{filename}.sta"
        return f"D:{filename}"
