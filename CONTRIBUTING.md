# Contributing to SmithPilot

Thanks for contributing. SmithPilot controls laboratory equipment, so changes
must preserve operator control and make hardware effects explicit.

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Run the application in mock mode when an analyzer is not available:

```powershell
python main.py
```

## Before Opening a Pull Request

```powershell
python -m ruff check .
python -m unittest discover -s tests
python -m compileall -q app instrument tests main.py
```

Keep changes focused and add tests for behavior changes. Do not include local
logs, captures, analyzer state files, credentials, or organization-specific
measurement data.

## Instrument Changes

- Keep all direct SCPI I/O in `instrument/e5071c.py`.
- Validate user-controlled values before including them in SCPI commands.
- Use mock or fake-session tests to verify command order and error handling.
- Document the exact analyzer model and firmware used for hardware validation.
- Do not automate calibration, state overwrite, or powered RF operations
  without an explicit operator action and clear UI warning.

See [Hardware Validation](docs/HARDWARE_VALIDATION.md) before testing against a
real analyzer.

## Pull Requests

Describe the problem, the chosen approach, tests run, and any hardware
validation. UI changes should include a screenshot. Hardware-dependent changes
must state whether they were tested only in mock mode or on a real E5071C.

By contributing, you agree that your contribution is licensed under the MIT
License.
