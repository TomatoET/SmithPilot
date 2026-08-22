# SmithPilot V0.4 Workflow PRD

## Problem Statement

SmithPilot V0.1 can validate LAN/SCPI communication with an Agilent/Keysight
E5071C VNA, but it does not cover the complete two-port measurement workflow.
Engineers still need to manually configure
traces, markers, calibration, port extension, trace memory references, result
capture, and impedance-matching notes on the instrument.

## Solution

Build SmithPilot as a semi-automatic E5071C workflow assistant. The
software will configure the analyzer, guide the operator through physical
connection steps, execute only the SCPI action for the currently confirmed
step, read back system errors, manage trace memory references, capture named
screen images, and save logs/data for later comparison.

SmithPilot is intentionally not a fully automatic matching optimizer. Any action that
requires physical standards, DUT wiring, PA removal, platform RF path changes,
or instrument state overwrite remains operator-confirmed.

## User Stories

1. As an RF engineer, I want to select a known TX band preset, so that start,
   stop, points, and marker frequencies are configured consistently.
2. As an RF engineer, I want to manually edit start, stop, points, and markers,
   so that I can handle custom frequency spans.
3. As an RF engineer, I want one command to configure three traces as S11 Smith,
   S22 Smith, and S21 Log Mag, so that the analyzer matches the requested
   workflow.
4. As an RF engineer, I want a mechanical calibration wizard, so that Open,
   Short, Load, and Thru operations happen in the right order.
5. As an RF engineer, I want each calibration step to show the required
   physical connection before SCPI is sent, so that standards are not measured
   in the wrong state.
6. As an RF engineer, I want to run 2-port ECal with a connected USB ECal
   module, so that I can calibrate faster when electronic calibration hardware
   is available.
7. As an RF engineer, I want to list and select connected ECal modules, so that
   the analyzer uses the intended module when multiple modules may exist.
8. As an RF engineer, I want ECal auto-orientation control, so that the analyzer
   can detect the module orientation unless I intentionally disable it.
9. As an RF engineer, I want to run an ECal confidence check, so that I can
   verify the current electronic calibration path.
10. As an RF engineer, I want SmithPilot to read `SYST:ERR?` after critical
   steps, so that I can catch analyzer-side mistakes immediately.
11. As an RF engineer, I want to save and recall state files with clear warnings,
   so that known-good calibration and port-extension states can be reused.
12. As an RF engineer, I want an Auto Port Extension wizard, so that fixture
   cable delay and loss compensation can be applied after calibration.
13. As an RF engineer, I want the software to record port extension time and
   loss values, so that the compensation is traceable.
14. As an RF engineer, I want to display Trace 1-3 data and memory traces
    together, so that I can compare the current sweep against a reference.
15. As an RF engineer, I want one command to copy Trace 1-3 data into memory,
    so that a reference trace can be captured without manually operating each
    trace on the analyzer.
16. As an RF engineer, I want to name and save analyzer screen captures on the
    PC, so that matching iterations can be documented without manual file
    transfer.
17. As an RF engineer, I want a configurable VNA image folder, so that the same
    screen capture is archived on the analyzer and transferred to the PC.
18. As an RF engineer, I want to save a communication log, so that VNA actions
    can be audited after the measurement.
19. As an RF engineer, I want mock mode to support the workflow, so that UI
    and process validation can happen without occupying the real analyzer.

## Implementation Decisions

- Keep all direct SCPI I/O inside the E5071C driver.
- Keep user-entered arbitrary console writes under the existing safety policy.
- Add explicit driver methods for workflow actions instead of opening a broad SCPI
  write surface.
- Add a pure workflow module for frequency bands, trace setup, and calibration
  steps.
- Load Setup page band presets from `config/band_presets.json` using a uniform
  editable format: name, unit, start, stop, points, and markers.
- Add controlled ECal methods for module catalog, module selection,
  auto-orientation, 2-port SOLT ECal, and confidence check.
- The Electronic ECal UI fixes the calibration ports to Port 1 - Port 2 for the
  current two-port workflow instead of exposing editable port fields.
- Auto Port Extension provides three explicit port choices: Port 1, Port 2, and
  All. Clear the E5071C Port 1/2 auto-extension selection before enabling the
  requested port(s) so stale analyzer checkmarks do not affect measurement.
- Use a tabbed PySide6 UI: Connection, Setup, Calibration, Port
  Extension, Measurement Tools, and Log.
- Split the Calibration tab into Mechanical SOLT, Electronic ECal, and State
  sub-tabs so manual calibration, ECal, and analyzer state management remain
  visually separate.
- Save/Recall becomes a controlled feature with warnings and explicit file
  names. State overwrite is never implicit.
- The workflow relies on E5071C-compatible commands documented by Keysight, including
  `:CALC1:PAR:COUN`, `:CALC1:PARn:DEF`, `:CALC1:FORM`, mechanical SOLT
  commands under `:SENS1:CORR:COLL`, ECal commands under
  `:SYST:COMM:ECAL` and `:SENS1:CORR:COLL:ECAL`, Auto Port Extension commands
  under `:SENS1:CORR:EXT:AUTO`, state save/load under `:MMEM`, trace
  data/memory display under `:DISP:WIND1:TRACn:STAT` and
  `:DISP:WIND1:TRACn:MEM`, and Data -> Mem capture under
  `:CALC1:PARn:SEL` followed by `:CALC1:MATH:MEM`. Screen capture ensures the
  configured VNA folder exists with `:MMEM:CAT?` and `:MMEM:MDIR`, saves the
  PNG/BMP image with `:MMEM:STOR:IMAG`, and transfers that file to the PC with
  `:MMEM:TRAN?` while retaining the VNA copy.

## Testing Decisions

- Test pure workflow behavior with standard `unittest` so the project does not
  need another dependency.
- Test the SCPI command sequence through a fake session at the E5071C public
  method layer; do not test private parsing helpers.
- Do not run mechanical calibration or ECal against the real analyzer during
  automated tests, because they depend on physical standards, ECal modules, and
  operator timing.
- Use real hardware only for low-risk smoke checks such as connection and
  read-only identity/query operations unless the operator explicitly requests a
  calibration run.

## Out of Scope

- Automatic PA/platform control.
- Fully automatic physical calibration.
- Automatic component selection or board modification.
- Factory reset or unattended preset.
- Overwriting instrument state without explicit operator intent.
- Full local Smith chart rendering and optimizer.

## Further Notes

- The reference workflow uses an E5071C and an 85032F mechanical calibration kit.
- ECal is an alternate calibration path when a compatible USB ECal module is
  available.
- Default band presets should be treated as editable starting points and kept in
  `config/band_presets.json` for manual additions.
- The workflow should favor traceability and safety over speed.
