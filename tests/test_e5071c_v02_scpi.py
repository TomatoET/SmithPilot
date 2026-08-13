from __future__ import annotations

import unittest

from app.vna_workflow import default_trace_setup
from instrument import E5071C, InstrumentSafetyError


class E5071CV02ScpiTests(unittest.TestCase):
    def make_driver(self) -> tuple[E5071C, list[tuple[str, str]]]:
        events: list[tuple[str, str]] = []
        driver = E5071C(mock=True, log_callback=lambda kind, message: events.append((kind, message)))
        driver.connect()
        events.clear()
        return driver, events

    def tx_messages(self, events: list[tuple[str, str]]) -> list[str]:
        return [message for kind, message in events if kind == "TX"]

    def test_configure_v02_measurement_sets_three_pdf_traces_and_markers(self) -> None:
        driver, events = self.make_driver()

        driver.configure_v02_measurement(
            start_hz=1_920_000_000.0,
            stop_hz=1_980_000_000.0,
            points=1601,
            marker_hz=(1_920_000_000.0, 1_950_000_000.0, 1_980_000_000.0),
            traces=default_trace_setup(),
        )

        tx = self.tx_messages(events)
        self.assertIn(":CALC1:PAR:COUN 3", tx)
        self.assertIn(":CALC1:PAR1:DEF S11", tx)
        self.assertIn(":CALC1:FORM SMIT", tx)
        self.assertIn(":CALC1:PAR2:DEF S22", tx)
        self.assertIn(":CALC1:PAR3:DEF S21", tx)
        self.assertIn(":CALC1:FORM MLOG", tx)
        self.assertIn(":CALC1:TRAC3:MARK3:X 1980000000", tx)
        self.assertIn(":DISP:TABL OFF", tx)
        self.assertNotIn(":DISP:TABL ON", tx)
        self.assertNotIn(":DISP:TABL:TYPE MARK", tx)

    def test_two_port_calibration_methods_emit_confirmed_steps_only(self) -> None:
        driver, events = self.make_driver()

        driver.start_two_port_solt_calibration(cal_kit="85032F")
        driver.acquire_calibration_standard("OPEN", (1,))
        driver.acquire_calibration_standard("SHOR", (2,))
        driver.acquire_calibration_standard("LOAD", (2,))
        driver.acquire_calibration_standard("THRU", (1, 2))
        driver.save_calibration()

        tx = self.tx_messages(events)
        self.assertIn(':SENS1:CORR:COLL:CKIT "85032F"', tx)
        self.assertIn(":SENS1:CORR:COLL:METH:SOLT2 1,2", tx)
        self.assertIn(":SENS1:CORR:COLL:OPEN 1", tx)
        self.assertIn(":SENS1:CORR:COLL:SHOR 2", tx)
        self.assertIn(":SENS1:CORR:COLL:LOAD 2", tx)
        self.assertIn(":SENS1:CORR:COLL:THRU 1,2", tx)
        self.assertIn(":SENS1:CORR:COLL:SAVE", tx)

    def test_electronic_calibration_lists_selects_and_runs_two_port_ecal(self) -> None:
        driver, events = self.make_driver()

        modules = driver.list_ecal_modules()
        driver.select_ecal_module(modules[0])
        driver.set_ecal_auto_orientation(True)
        driver.perform_two_port_ecal((1, 2))
        driver.perform_ecal_confidence_check()

        tx = self.tx_messages(events)
        self.assertIn(":SYST:COMM:ECAL:CAT?", tx)
        self.assertIn(':SYST:COMM:ECAL:DEF "N4431B 03605"', tx)
        self.assertIn(":SENS1:CORR:COLL:ECAL:ORI ON", tx)
        self.assertIn(":SENS1:CORR:COLL:ECAL:SOLT2 1,2", tx)
        self.assertIn(":SENS1:CORR:COLL:ECAL:CCH", tx)

        with self.assertRaises(InstrumentSafetyError):
            driver.write(":SENS1:CORR:COLL:ECAL:SOLT2 1,2")

    def test_auto_port_extension_records_analyzer_result(self) -> None:
        driver, events = self.make_driver()

        driver.configure_auto_port_extension(port=1, include_loss=True, adjust_mismatch=False)
        driver.measure_auto_port_extension(port=1, standard="OPEN")
        result = driver.get_port_extension_result(port=1)

        tx = self.tx_messages(events)
        self.assertIn(":SENS1:CORR:EXT ON", tx)
        self.assertIn(":SENS1:CORR:EXT:AUTO:PORT1 OFF", tx)
        self.assertIn(":SENS1:CORR:EXT:AUTO:PORT2 OFF", tx)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:PORT1 ON"), 2)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:PORT2 ON"), 0)
        self.assertIn(":SENS1:CORR:EXT:AUTO:LOSS ON", tx)
        self.assertIn(":SENS1:CORR:EXT:AUTO:DCOF OFF", tx)
        self.assertIn(":SENS1:CORR:EXT:AUTO:MEAS OPEN", tx)
        self.assertEqual(result.port, 1)

    def test_auto_port_extension_all_ports_selects_both_ports(self) -> None:
        driver, events = self.make_driver()

        driver.configure_auto_port_extension_ports(
            ports=(1, 2),
            include_loss=True,
            adjust_mismatch=False,
        )
        driver.measure_auto_port_extension_ports(ports=(1, 2), standard="OPEN")
        results = driver.get_port_extension_results(ports=(1, 2))

        tx = self.tx_messages(events)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:PORT1 OFF"), 2)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:PORT2 OFF"), 2)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:PORT1 ON"), 2)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:PORT2 ON"), 2)
        self.assertEqual(tx.count(":SENS1:CORR:EXT:AUTO:MEAS OPEN"), 1)
        self.assertEqual([result.port for result in results], [1, 2])

    def test_state_save_recall_is_driver_controlled_not_console_write(self) -> None:
        driver, events = self.make_driver()

        driver.save_state("smithpilot_b1", save_type="CDST")
        driver.recall_state("smithpilot_b1")

        tx = self.tx_messages(events)
        self.assertIn(":MMEM:STOR:STYP CDST", tx)
        self.assertIn(':MMEM:STOR "D:smithpilot_b1.sta"', tx)
        self.assertIn(':MMEM:LOAD "D:smithpilot_b1.sta"', tx)

        with self.assertRaises(InstrumentSafetyError):
            driver.write(':MMEM:STOR "D:unsafe.sta"')


if __name__ == "__main__":
    unittest.main()
