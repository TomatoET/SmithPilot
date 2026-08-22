## Summary

Describe the problem and the change.

## Validation

- [ ] `python -m ruff check .`
- [ ] `python -m unittest discover -s tests`
- [ ] `python -m compileall -q app instrument tests main.py`
- [ ] UI changes include a screenshot
- [ ] Hardware validation level is stated, or this change does not affect SCPI

## Hardware Impact

List affected SCPI commands, analyzer state changes, and the validation level
from `docs/HARDWARE_VALIDATION.md`.
