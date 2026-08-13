from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import hypot
from pathlib import Path
from typing import Any


BAND_PRESETS_PATH = Path(__file__).resolve().parent.parent / "config" / "band_presets.json"

_PRESET_UNIT_MULTIPLIERS = {
    "hz": 1.0,
    "khz": 1_000.0,
    "mhz": 1_000_000.0,
    "ghz": 1_000_000_000.0,
}


@dataclass(frozen=True)
class FrequencyBand:
    name: str
    start_hz: float
    stop_hz: float
    marker_hz: tuple[float, ...]
    points: int = 1601


@dataclass(frozen=True)
class TraceSetup:
    trace: int
    measurement: str
    display_format: str
    label: str


@dataclass(frozen=True)
class CalibrationStep:
    action: str
    title: str
    instruction: str
    cal_kit: str = ""
    standard: str = ""
    ports: tuple[int, ...] = ()
    requires_user_confirmation: bool = True


@dataclass(frozen=True)
class ECalPlan:
    kind: str = "2-Port ECal"
    ports: tuple[int, int] = (1, 2)
    auto_orientation: bool = True


@dataclass(frozen=True)
class PortExtensionPlan:
    port: int
    include_loss: bool = True
    adjust_mismatch: bool = False
    method: str = "CSPN"
    standard: str = "OPEN"


@dataclass(frozen=True)
class PortExtensionResult:
    port: int
    delay_s: float
    loss1_db: float
    loss2_db: float
    freq1_hz: float
    freq2_hz: float


@dataclass(frozen=True)
class DutChecklist:
    pa_removed: bool = False
    port1_soldered: bool = False
    port2_connected: bool = False
    platform_path_open: bool = False
    no_high_power_confirmed: bool = False

    def is_ready(self) -> bool:
        return not self.missing_items()

    def missing_items(self) -> list[str]:
        missing: list[str] = []
        if not self.pa_removed:
            missing.append("Remove the PA or isolate the active device from the measurement path.")
        if not self.port1_soldered:
            missing.append("Connect Port 1 to the DUT-side PA output node.")
        if not self.port2_connected:
            missing.append("Connect Port 2 to the antenna-side RF test port.")
        if not self.platform_path_open:
            missing.append("Open the required RF path in the platform tool.")
        if not self.no_high_power_confirmed:
            missing.append("Confirm there is no high-power RF output before VNA measurement.")
        return missing


@dataclass(frozen=True)
class MarkerReading:
    trace: str
    marker: int
    frequency_hz: float
    primary: float
    secondary: float


@dataclass(frozen=True)
class MeasurementJudgement:
    severity: str
    findings: list[str] = field(default_factory=list)


def default_trace_setup() -> tuple[TraceSetup, ...]:
    return (
        TraceSetup(1, "S11", "SMIT", "Trace 1: S11 Smith"),
        TraceSetup(2, "S22", "SMIT", "Trace 2: S22 Smith"),
        TraceSetup(3, "S21", "MLOG", "Trace 3: S21 Log Mag"),
    )


def default_ecal_plan() -> ECalPlan:
    return ECalPlan()


def builtin_band_presets() -> tuple[FrequencyBand, ...]:
    return (
        FrequencyBand(
            "WCDMA B1 TX",
            1_920_000_000.0,
            1_980_000_000.0,
            (1_920_000_000.0, 1_950_000_000.0, 1_980_000_000.0),
        ),
        FrequencyBand(
            "WCDMA B2 TX",
            1_850_000_000.0,
            1_910_000_000.0,
            (1_850_000_000.0, 1_880_000_000.0, 1_910_000_000.0),
        ),
        FrequencyBand(
            "WCDMA B5 TX",
            824_000_000.0,
            849_000_000.0,
            (824_000_000.0, 836_500_000.0, 849_000_000.0),
        ),
        FrequencyBand(
            "WCDMA B8 TX",
            880_000_000.0,
            915_000_000.0,
            (880_000_000.0, 897_500_000.0, 915_000_000.0),
        ),
        FrequencyBand(
            "LTE B1 TX",
            1_920_000_000.0,
            1_980_000_000.0,
            (1_920_000_000.0, 1_950_000_000.0, 1_980_000_000.0),
        ),
        FrequencyBand(
            "LTE B38 TX",
            2_570_000_000.0,
            2_620_000_000.0,
            (2_570_000_000.0, 2_595_000_000.0, 2_620_000_000.0),
        ),
        FrequencyBand(
            "LTE B40 TX",
            2_300_000_000.0,
            2_400_000_000.0,
            (2_300_000_000.0, 2_350_000_000.0, 2_400_000_000.0),
        ),
    )


def default_band_presets() -> tuple[FrequencyBand, ...]:
    if BAND_PRESETS_PATH.exists():
        return load_band_presets(BAND_PRESETS_PATH)
    return builtin_band_presets()


def load_band_presets(path: str | Path) -> tuple[FrequencyBand, ...]:
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_bands = payload.get("bands")
    else:
        raw_bands = payload
    if not isinstance(raw_bands, list):
        raise ValueError("Band preset file must contain a 'bands' list.")

    bands = tuple(_parse_band_preset(raw_band, index + 1) for index, raw_band in enumerate(raw_bands))
    if not bands:
        raise ValueError("Band preset file must contain at least one band.")
    return bands


def _parse_band_preset(raw_band: Any, index: int) -> FrequencyBand:
    if not isinstance(raw_band, dict):
        raise ValueError(f"Band preset #{index} must be an object.")

    name = _required_text(raw_band, "name", index)
    unit = _required_text(raw_band, "unit", index).lower()
    if unit not in _PRESET_UNIT_MULTIPLIERS:
        raise ValueError(f"Band preset '{name}' uses unsupported unit '{unit}'.")
    multiplier = _PRESET_UNIT_MULTIPLIERS[unit]

    start_hz = _required_number(raw_band, "start", index) * multiplier
    stop_hz = _required_number(raw_band, "stop", index) * multiplier
    if start_hz >= stop_hz:
        raise ValueError(f"Band preset '{name}' start must be less than stop.")

    marker_values = raw_band.get("markers")
    if not isinstance(marker_values, list):
        raise ValueError(f"Band preset '{name}' must contain a markers list.")
    if not marker_values:
        raise ValueError(f"Band preset '{name}' must contain at least one marker.")
    if len(marker_values) > 10:
        raise ValueError(f"Band preset '{name}' cannot contain more than 10 markers.")

    marker_hz = tuple(_number_from_value(value, "markers", index) * multiplier for value in marker_values)
    for marker in marker_hz:
        if marker < start_hz or marker > stop_hz:
            raise ValueError(f"Band preset '{name}' marker must be inside sweep span.")

    points_raw = raw_band.get("points", 1601)
    if isinstance(points_raw, bool) or not isinstance(points_raw, int):
        raise ValueError(f"Band preset '{name}' points must be an integer.")
    if points_raw < 2:
        raise ValueError(f"Band preset '{name}' points must be at least 2.")

    return FrequencyBand(name, start_hz, stop_hz, marker_hz, points_raw)


def _required_text(raw_band: dict[str, Any], field_name: str, index: int) -> str:
    value = raw_band.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Band preset #{index} must contain a non-empty '{field_name}'.")
    return value.strip()


def _required_number(raw_band: dict[str, Any], field_name: str, index: int) -> float:
    if field_name not in raw_band:
        raise ValueError(f"Band preset #{index} must contain '{field_name}'.")
    return _number_from_value(raw_band[field_name], field_name, index)


def _number_from_value(value: Any, field_name: str, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Band preset #{index} field '{field_name}' must be a number.")
    return float(value)


def build_two_port_calibration_steps(cal_kit: str = "85032F") -> tuple[CalibrationStep, ...]:
    return (
        CalibrationStep(
            "start_two_port_solt",
            "Start 2-Port SOLT",
            f"Select calibration kit {cal_kit} and prepare mechanical 2-port SOLT calibration.",
            cal_kit=cal_kit,
            requires_user_confirmation=False,
        ),
        CalibrationStep(
            "measure_open_p1",
            "Port 1 Open",
            "Connect OPEN standard to Port 1, then acquire OPEN.",
            cal_kit=cal_kit,
            standard="OPEN",
            ports=(1,),
        ),
        CalibrationStep(
            "measure_short_p1",
            "Port 1 Short",
            "Connect SHORT standard to Port 1, then acquire SHORT.",
            cal_kit=cal_kit,
            standard="SHOR",
            ports=(1,),
        ),
        CalibrationStep(
            "measure_load_p1",
            "Port 1 Load",
            "Connect LOAD standard to Port 1, then acquire LOAD.",
            cal_kit=cal_kit,
            standard="LOAD",
            ports=(1,),
        ),
        CalibrationStep(
            "measure_open_p2",
            "Port 2 Open",
            "Connect OPEN standard to Port 2, then acquire OPEN.",
            cal_kit=cal_kit,
            standard="OPEN",
            ports=(2,),
        ),
        CalibrationStep(
            "measure_short_p2",
            "Port 2 Short",
            "Connect SHORT standard to Port 2, then acquire SHORT.",
            cal_kit=cal_kit,
            standard="SHOR",
            ports=(2,),
        ),
        CalibrationStep(
            "measure_load_p2",
            "Port 2 Load",
            "Connect LOAD standard to Port 2, then acquire LOAD.",
            cal_kit=cal_kit,
            standard="LOAD",
            ports=(2,),
        ),
        CalibrationStep(
            "measure_thru_p1_p2",
            "Port 1-2 Thru",
            "Connect THRU between Port 1 and Port 2, then acquire THRU.",
            cal_kit=cal_kit,
            standard="THRU",
            ports=(1, 2),
        ),
        CalibrationStep(
            "save_calibration",
            "Save Calibration",
            "Save the completed calibration coefficients on the analyzer.",
            cal_kit=cal_kit,
            standard="SAVE",
            requires_user_confirmation=False,
        ),
    )


def judge_marker_results(readings: list[MarkerReading]) -> MeasurementJudgement:
    findings: list[str] = []
    for reading in readings:
        trace = reading.trace.upper()
        if trace in {"S11", "S22"}:
            distance = hypot(reading.primary - 50.0, reading.secondary)
            if distance > 25.0:
                findings.append(
                    f"{trace} marker {reading.marker} is far from 50 ohm "
                    f"({reading.primary:.2f} + j{reading.secondary:.2f} ohm)."
                )
        elif trace == "S21" and reading.primary < -3.0:
            findings.append(
                f"S21 marker {reading.marker} Loss is high ({reading.primary:.2f} dB)."
            )

    if findings:
        return MeasurementJudgement("warning", findings)
    return MeasurementJudgement("ok", ["Markers are within the initial V0.2 judgement limits."])
