from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace

from app.vna_workflow import default_trace_setup
from instrument import E5071C, InstrumentCommandError, InstrumentSafetyError


class E5071CV02ScpiTests(unittest.TestCase):
    def test_default_lan_resource_uses_scpi_socket_port(self) -> None:
        self.assertEqual(
            E5071C.build_resource("192.0.2.10"),
            "TCPIP0::192.0.2.10::5025::SOCKET",
        )

    def test_connect_falls_back_to_vxi11_resource_when_socket_times_out(self) -> None:
        events: list[tuple[str, str]] = []
        attempts: list[str] = []
        socket_resource = "TCPIP0::192.0.2.10::5025::SOCKET"
        vxi11_resource = "TCPIP0::192.0.2.10::inst0::INSTR"

        class FakeSession:
            def __init__(self, resource: str) -> None:
                self.resource = resource
                self.timeout = 0
                self.write_termination = ""
                self.read_termination = ""
                self.closed = False

            def query(self, command: str) -> str:
                if self.resource == socket_resource and command == "*IDN?":
                    raise TimeoutError("VI_ERROR_TMO simulated")
                if command == "*IDN?":
                    return "Agilent Technologies,E5071C,MY123,A.11.01"
                if command == "SYST:ERR?":
                    return '+0,"No error"'
                raise AssertionError(f"Unexpected query: {command}")

            def close(self) -> None:
                self.closed = True

        class FakeResourceManager:
            def open_resource(self, resource: str) -> FakeSession:
                attempts.append(resource)
                return FakeSession(resource)

            def close(self) -> None:
                pass

        original_pyvisa = sys.modules.get("pyvisa")
        fake_rm = FakeResourceManager()
        sys.modules["pyvisa"] = SimpleNamespace(ResourceManager=lambda _backend: fake_rm)
        try:
            driver = E5071C(
                ip_address="192.0.2.10",
                timeout_ms=5000,
                log_callback=lambda kind, message: events.append((kind, message)),
            )

            identity = driver.connect()
        finally:
            if original_pyvisa is None:
                sys.modules.pop("pyvisa", None)
            else:
                sys.modules["pyvisa"] = original_pyvisa

        self.assertEqual(attempts, [socket_resource, vxi11_resource])
        self.assertEqual(driver.resource, vxi11_resource)
        self.assertEqual(identity.model, "E5071C")
        self.assertTrue(driver.is_connected())
        self.assertIn(("Connection", f"Opening VISA resource: {socket_resource}"), events)
        self.assertIn(("Connection", f"Opening VISA resource: {vxi11_resource}"), events)

    def make_driver(self) -> tuple[E5071C, list[tuple[str, str]]]:
        events: list[tuple[str, str]] = []
        driver = E5071C(
            mock=True, log_callback=lambda kind, message: events.append((kind, message))
        )
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

    def test_trace_memory_tools_show_data_memory_and_copy_all_three_traces(self) -> None:
        driver, events = self.make_driver()

        driver.display_traces_data_and_memory(traces=(1, 2, 3))
        driver.copy_traces_data_to_memory(traces=(1, 2, 3))

        tx = self.tx_messages(events)
        self.assertEqual(
            tx,
            [
                ":DISP:WIND1:TRAC1:STAT ON",
                ":DISP:WIND1:TRAC1:MEM ON",
                ":DISP:WIND1:TRAC2:STAT ON",
                ":DISP:WIND1:TRAC2:MEM ON",
                ":DISP:WIND1:TRAC3:STAT ON",
                ":DISP:WIND1:TRAC3:MEM ON",
                "SYST:ERR?",
                ":CALC1:PAR1:SEL",
                ":CALC1:MATH:MEM",
                ":CALC1:PAR2:SEL",
                ":CALC1:MATH:MEM",
                ":CALC1:PAR3:SEL",
                ":CALC1:MATH:MEM",
                "SYST:ERR?",
            ],
        )

    def test_trace_memory_error_is_drained_before_next_operation(self) -> None:
        class ErrorQueueSession:
            def __init__(self) -> None:
                self.errors: list[str] = []

            def write(self, command: str) -> None:
                if command.endswith(":MEM ON"):
                    self.errors.append('+52,"No valid memory trace"')

            def query(self, command: str) -> str:
                if command == "SYST:ERR?":
                    return self.errors.pop(0) if self.errors else '+0,"No error"'
                raise AssertionError(f"Unexpected query: {command}")

        session = ErrorQueueSession()
        driver = E5071C(ip_address="192.0.2.10")
        driver._connected = True
        driver._session = session

        with self.assertRaisesRegex(InstrumentCommandError, "No valid memory trace"):
            driver.display_traces_data_and_memory(traces=(1, 2, 3))

        self.assertEqual(session.errors, [])
        driver.copy_traces_data_to_memory(traces=(1, 2, 3))

    def test_screen_capture_can_be_pulled_to_pc_and_saved_on_vna(self) -> None:
        driver, events = self.make_driver()

        image = driver.capture_screen_image(
            image_format="PNG",
            vna_path="D:\\SmithPilot\\Images\\B34_before.png",
            keep_vna_copy=True,
        )

        self.assertTrue(image.startswith(b"\x89PNG"))
        tx = self.tx_messages(events)
        self.assertEqual(
            tx,
            [
                ':MMEM:CAT? "D:\\"',
                "SYST:ERR?",
                ':MMEM:MDIR "D:\\SmithPilot"',
                "SYST:ERR?",
                ':MMEM:CAT? "D:\\SmithPilot"',
                "SYST:ERR?",
                ':MMEM:MDIR "D:\\SmithPilot\\Images"',
                "SYST:ERR?",
                ':MMEM:STOR:IMAG "D:\\SmithPilot\\Images\\B34_before.png"',
                "*OPC?",
                "SYST:ERR?",
                ':MMEM:TRAN? "D:\\SmithPilot\\Images\\B34_before.png"',
            ],
        )

    def test_screen_capture_creates_missing_vna_directories(self) -> None:
        driver, events = self.make_driver()

        driver.capture_screen_image(
            image_format="PNG",
            vna_path="D:\\SmithPilot\\Images\\capture.png",
            keep_vna_copy=True,
        )

        tx = self.tx_messages(events)
        self.assertIn(':MMEM:MDIR "D:\\SmithPilot"', tx)
        self.assertIn(':MMEM:MDIR "D:\\SmithPilot\\Images"', tx)
        self.assertLess(
            tx.index(':MMEM:MDIR "D:\\SmithPilot\\Images"'),
            tx.index(':MMEM:STOR:IMAG "D:\\SmithPilot\\Images\\capture.png"'),
        )

    def test_screen_capture_without_vna_copy_uses_temporary_vna_file(self) -> None:
        driver, events = self.make_driver()

        image = driver.capture_screen_image(image_format="BMP")

        self.assertTrue(image.startswith(b"BM"))
        tx = self.tx_messages(events)
        self.assertEqual(
            tx,
            [
                ':MMEM:STOR:IMAG "D:SmithPilotCaptureTemp.bmp"',
                "*OPC?",
                "SYST:ERR?",
                ':MMEM:TRAN? "D:SmithPilotCaptureTemp.bmp"',
                ':MMEM:DEL "D:SmithPilotCaptureTemp.bmp"',
                "SYST:ERR?",
            ],
        )

    def test_screen_capture_uses_vna_file_transfer_not_hardcopy_query(self) -> None:
        events: list[tuple[str, str]] = []
        image = b"\x89PNG\r\n\x1a\nfake-e5071c-screen-capture"

        class FakeSession:
            def __init__(self) -> None:
                self.commands: list[tuple[str, str]] = []
                self._used_hardcopy_query = False
                size = str(len(image)).encode("ascii")
                self._binary_response = b"#" + str(len(size)).encode("ascii") + size + image + b"\n"

            def write(self, command: str) -> None:
                self.commands.append(("write", command))
                if command.startswith(":HCOP:SDUM:DATA?"):
                    self._used_hardcopy_query = True

            def query(self, command: str) -> str:
                self.commands.append(("query", command))
                if command == ':MMEM:CAT? "D:\\"':
                    return "263499776,10222256128,Agilent\\,,0,Leo\\,,0,State\\,,0"
                if command == "*OPC?":
                    return "1"
                if command == "SYST:ERR?":
                    if self._used_hardcopy_query:
                        return '-420,"Query UNTERMINATED"'
                    return '+0,"No error"'
                raise AssertionError(f"Unexpected query: {command}")

            def read_bytes(self, count: int) -> bytes:
                chunk = self._binary_response[:count]
                self._binary_response = self._binary_response[count:]
                if len(chunk) != count:
                    raise AssertionError(f"Expected {count} bytes, got {len(chunk)}")
                return chunk

        session = FakeSession()
        driver = E5071C(
            ip_address="192.0.2.10",
            log_callback=lambda kind, message: events.append((kind, message)),
        )
        driver._connected = True
        driver._session = session

        pulled_image = driver.capture_screen_image(
            image_format="PNG",
            vna_path="D:\\Leo\\screen_capture.png",
            keep_vna_copy=True,
        )

        self.assertEqual(pulled_image, image)
        tx = self.tx_messages(events)
        self.assertEqual(
            tx,
            [
                ':MMEM:CAT? "D:\\"',
                "SYST:ERR?",
                ':MMEM:STOR:IMAG "D:\\Leo\\screen_capture.png"',
                "*OPC?",
                "SYST:ERR?",
                ':MMEM:TRAN? "D:\\Leo\\screen_capture.png"',
            ],
        )
        self.assertFalse(any("HCOP:SDUM" in command for command in tx))

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
