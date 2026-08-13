from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.vna_workflow import (
    DutChecklist,
    MarkerReading,
    build_two_port_calibration_steps,
    default_ecal_plan,
    default_band_presets,
    default_trace_setup,
    judge_marker_results,
    load_band_presets,
)


TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp"


class VnaWorkflowTests(unittest.TestCase):
    def test_default_band_presets_include_pdf_tx_bands(self) -> None:
        bands = {band.name: band for band in default_band_presets()}

        b1 = bands["WCDMA B1 TX"]
        self.assertEqual(b1.start_hz, 1_920_000_000.0)
        self.assertEqual(b1.stop_hz, 1_980_000_000.0)
        self.assertEqual(b1.marker_hz, (1_920_000_000.0, 1_950_000_000.0, 1_980_000_000.0))

        self.assertIn("LTE B38 TX", bands)
        self.assertIn("LTE B40 TX", bands)
        lte_b1 = bands["LTE B1 TX"]
        self.assertEqual(lte_b1.start_hz, 1_920_000_000.0)
        self.assertEqual(lte_b1.stop_hz, 1_980_000_000.0)

    def test_load_band_presets_reads_editable_json_format(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        path = TEST_TMP_ROOT / "test_band_presets_valid.json"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "bands": [
                        {
                            "name": "Custom B1 TX",
                            "unit": "MHz",
                            "start": 1920,
                            "stop": 1980,
                            "points": 1601,
                            "markers": [1920, 1950, 1980],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        presets = load_band_presets(path)

        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0].name, "Custom B1 TX")
        self.assertEqual(presets[0].start_hz, 1_920_000_000.0)
        self.assertEqual(presets[0].stop_hz, 1_980_000_000.0)
        self.assertEqual(
            presets[0].marker_hz,
            (1_920_000_000.0, 1_950_000_000.0, 1_980_000_000.0),
        )

    def test_load_band_presets_rejects_markers_outside_span(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        path = TEST_TMP_ROOT / "test_band_presets_invalid.json"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "bands": [
                        {
                            "name": "Bad Band",
                            "unit": "MHz",
                            "start": 1920,
                            "stop": 1980,
                            "points": 1601,
                            "markers": [1910],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_band_presets(path)

    def test_default_trace_setup_uses_requested_order(self) -> None:
        traces = default_trace_setup()

        self.assertEqual(
            [(trace.trace, trace.measurement, trace.display_format) for trace in traces],
            [(1, "S11", "SMIT"), (2, "S22", "SMIT"), (3, "S21", "MLOG")],
        )

    def test_two_port_calibration_steps_follow_pdf_order(self) -> None:
        steps = build_two_port_calibration_steps(cal_kit="85032F")

        actions = [step.action for step in steps]
        self.assertEqual(
            actions,
            [
                "start_two_port_solt",
                "measure_open_p1",
                "measure_short_p1",
                "measure_load_p1",
                "measure_open_p2",
                "measure_short_p2",
                "measure_load_p2",
                "measure_thru_p1_p2",
                "save_calibration",
            ],
        )
        self.assertTrue(all(step.requires_user_confirmation for step in steps[1:8]))
        self.assertEqual(steps[0].cal_kit, "85032F")

    def test_default_ecal_plan_uses_two_port_auto_orientation(self) -> None:
        plan = default_ecal_plan()

        self.assertEqual(plan.ports, (1, 2))
        self.assertTrue(plan.auto_orientation)
        self.assertEqual(plan.kind, "2-Port ECal")

    def test_dut_checklist_requires_all_safety_items(self) -> None:
        checklist = DutChecklist()
        self.assertFalse(checklist.is_ready())

        complete = DutChecklist(
            pa_removed=True,
            port1_soldered=True,
            port2_connected=True,
            platform_path_open=True,
            no_high_power_confirmed=True,
        )
        self.assertTrue(complete.is_ready())

    def test_marker_judgement_flags_mismatch_and_loss(self) -> None:
        judgement = judge_marker_results(
            [
                MarkerReading("S11", 1, 1_920_000_000.0, 90.0, 25.0),
                MarkerReading("S22", 1, 1_920_000_000.0, 18.0, -20.0),
                MarkerReading("S21", 1, 1_920_000_000.0, -4.5, 0.0),
            ]
        )

        self.assertEqual(judgement.severity, "warning")
        self.assertTrue(any("S11" in item for item in judgement.findings))
        self.assertTrue(any("S22" in item for item in judgement.findings))
        self.assertTrue(any("S21" in item and "Loss" in item for item in judgement.findings))


if __name__ == "__main__":
    unittest.main()
