# SmithPilot

SmithPilot V0.2 is a Windows desktop application for semi-automatic
Agilent/Keysight E5071C vector network analyzer workflows. It keeps the V0.1
LAN/SCPI validation tools and adds the VNA workflow from the supplied Vanchip
usage PDF:

- V0.2 measurement setup with editable TX band presets and marker frequencies
- 3-trace analyzer setup: S11 Smith, S22 Smith, S21 Log Mag
- Mechanical 2-port SOLT calibration wizard for Open, Short, Load, and Thru
- Electronic 2-port calibration using a USB ECal module
- Controlled analyzer state Save/Recall
- Auto Port Extension setup, measurement, and readback
- DUT measurement checklist and S11/S22/S21 marker readback
- Basic result judgement for mismatch and insertion loss

V0.2 remains semi-automatic by design. It does not physically connect
standards, solder fixtures, control the external platform tool, enable PA
power, or automatically choose matching components.

## Technology

- Python 3.11+
- PySide6
- PyVISA
- PyVISA-py
- Standard-library `unittest` tests

## Project Structure

```text
SmithPilot/
|-- main.py
|-- requirements.txt
|-- README.md
|-- config/
|   `-- band_presets.json
|-- docs/
|   `-- v0.2_prd.md
|-- app/
|   |-- __init__.py
|   |-- main_window.py
|   |-- vna_workflow.py
|   `-- widgets/
|       `-- __init__.py
|-- instrument/
|   |-- __init__.py
|   |-- base_vna.py
|   `-- e5071c.py
|-- tests/
|   |-- test_e5071c_v02_scpi.py
|   |-- test_main_window_settings.py
|   `-- test_vna_workflow.py
`-- utils/
    |-- __init__.py
    `-- logger.py
```

## Install

Create and activate a Python environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you run `run_smithpilot.bat`, it uses `.venv\Scripts\python.exe` when that
environment exists; otherwise it uses `python` from PATH.

## Run

```powershell
python main.py
```

The application starts disconnected. It will not auto-connect to the instrument.

## E5071C LAN Connection

1. Connect the PC and E5071C to the same LAN or direct Ethernet link.
2. Confirm the E5071C IP address from the instrument LAN/network setup.
3. Enter the IP address in SmithPilot.
4. SmithPilot remembers the last non-empty IP address and restores it on the
   next launch.
5. SmithPilot builds the default VISA resource:

```text
TCPIP0::<IP>::inst0::INSTR
```

Example:

```text
TCPIP0::169.254.74.22::inst0::INSTR
```

SmithPilot uses PyVISA-py with `ResourceManager("@py")`.

## V0.2 Workflow

1. Connect to the E5071C.
2. Open `V0.2 Setup`.
3. Select a TX band preset or edit Start, Stop, Points, and Markers manually.
4. Click `Configure Analyzer` to set the 3-trace PDF workflow.
5. Open `Calibration`.
6. Open `Mechanical SOLT` for manual calibration and confirm the cal kit,
   default `85032F`.
7. Run each mechanical step only after the requested Open, Short, Load, or
   Thru connection is physically in place.
8. Or open `Electronic ECal`, connect the USB ECal module, click `Refresh ECal`,
   select the module, confirm the ECal is connected between Port 1 and Port 2,
   then click `Run 2-Port ECal`.
9. Optionally run `Confidence Check` after ECal.
10. Open `State` to optionally save or recall analyzer state using an explicit
   state file name.
11. Open `Port Extension`.
12. Choose `Port 1`, `Port 2`, or `All`, include loss if needed, connect OPEN
    at the selected extension reference plane(s), and measure Auto Port
    Extension. SmithPilot clears the E5071C Auto Port Extension Port 1/2
    selection before each measurement, then enables only the selected port(s).
13. Open `DUT Measurement`.
14. Complete the safety checklist, then run `Sweep + Read Markers`.
15. Review S11/S22/S21 marker values and the basic judgement text.

## Band Presets

Setup page band presets are loaded from:

```text
config/band_presets.json
```

The file uses one object per band:

```json
{
  "name": "WCDMA B1 TX",
  "unit": "MHz",
  "start": 1920,
  "stop": 1980,
  "points": 1601,
  "markers": [1920, 1950, 1980]
}
```

Supported units are `Hz`, `kHz`, `MHz`, and `GHz`. `markers` must be inside
the Start/Stop span and the E5071C supports up to 10 markers. After editing the
file while SmithPilot is open, click `Reload Presets` on the `V0.2 Setup` page.
If the file is missing, SmithPilot uses the built-in default presets. If the
file is invalid, SmithPilot keeps running with the built-in defaults and shows
a warning in the UI/log.

## Safety Policy

All direct instrument operations remain contained in `instrument/e5071c.py`.

The manual SCPI Console still blocks writes outside the narrow safe set used by
V0.1:

- Start Frequency
- Stop Frequency
- Sweep Points
- Single Sweep support commands

V0.2 adds controlled driver methods for mechanical calibration, ECal, port
extension, and Save/Recall. These methods validate inputs and are only called
by explicit UI buttons. Arbitrary console writes such as `:MMEM:STOR` or
`:SENS1:CORR:COLL:ECAL:SOLT2` remain blocked.

Do not run calibration or Auto Port Extension steps until the physical standard
or fixture state shown by the UI is actually connected. Do not run ECal until
the USB ECal module is selected and connected between VNA Port 1 and Port 2.

## Mock Instrument Mode

Use `Use Mock Instrument` when no real E5071C is connected. Mock mode is
clearly labeled in the UI and log and does not open a VISA resource. It supports
the V0.2 workflow enough to validate UI flow and command sequencing.

Mock identity:

```text
Manufacturer = Agilent Technologies
Model = E5071C
Serial = MOCK001
Firmware = MOCK
```

## Tests

Run the current regression suite:

```powershell
python -m unittest discover -s tests
```

The tests do not perform real mechanical calibration or ECal. Hardware
validation should start with read-only checks such as `*IDN?` and `SYST:ERR?`,
then proceed to calibration only when the operator is ready with the standards
or ECal module.

## Common Errors

### Wrapper not found: No package named pyvisa_py

The Python environment running SmithPilot does not have PyVISA-py installed.

Fix:

```powershell
pip install -r requirements.txt
```

### VI_ERROR_RSRC_NFOUND

The VISA resource cannot be found.

Check:

- The IP address is correct.
- PC and E5071C are on the same network.
- The resource string matches `TCPIP0::<IP>::inst0::INSTR`.

### Timeout

The instrument did not answer before the 5000 ms timeout.

Check:

- LAN cable and switch/direct connection.
- Instrument LAN settings.
- Whether another program is holding the instrument session.
- Whether the SCPI command is valid for the current analyzer state.

### Connection Refused

The PC reached the IP address, but the remote endpoint rejected the connection.

Check:

- E5071C remote control settings.
- Firewall rules.
- Whether the instrument supports the selected VISA LAN resource mode.

## Notes

- Single Sweep uses SCPI trigger/initiate commands and waits for `*OPC?`.
- V0.2 calibration and port extension commands also wait for operation complete
  where the E5071C reports completion.
- See `docs/v0.2_prd.md` for the implementation scope and out-of-scope list.
