# Hardware Validation

Automated tests use mock instruments and fake VISA sessions. They validate
command sequencing and parsing but cannot prove that every E5071C firmware
revision accepts the same SCPI form.

## Test Safety

1. Back up any analyzer state that must be preserved.
2. Disconnect active RF sources and confirm no high-power RF is present.
3. Start with read-only commands: `*IDN?` and `SYST:ERR?`.
4. Use a passive fixture or known load for the first configured sweep.
5. Run calibration only with the correct standards or ECal module connected.
6. Record the model, firmware, connection resource, command log, and result.

## Validation Levels

Use these labels in issues and pull requests:

- `mock`: exercised only with SmithPilot mock mode.
- `fake-session`: SCPI sequence verified by an automated fake VISA session.
- `hardware-smoke`: connection and non-destructive read/write checks passed.
- `hardware-workflow`: the complete affected workflow passed on an E5071C.

## Current Scope

The test suite covers setup, trace memory, screen capture transfer, mechanical
calibration sequencing, ECal sequencing, state operations, and Auto Port
Extension through mock or fake sessions. Treat each operation as requiring
hardware validation on the target instrument and firmware before production
use.

When reporting a hardware result, remove serial numbers, local file paths,
network addresses, DUT identifiers, and measurement data that should not be
public.
