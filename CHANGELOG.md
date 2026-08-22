# Changelog

All notable changes to SmithPilot are documented here. This project follows
[Semantic Versioning](https://semver.org/) from V0.4 onward.

## [Unreleased]

### Added

- Open-source project policies, contribution guidance, and GitHub automation.
- Simplified Chinese README with language navigation from the English README.

## [0.4.0] - 2026-08-21

### Added

- LTE Band 2 and Band 34 TX presets.
- Trace 1-3 Data/Memory display and one-click Data-to-Memory capture.
- Named PNG/BMP screen captures saved on the VNA and transferred to the PC.
- Persistent VNA and PC capture folders.
- Windows executable version metadata and bundled editable presets.

### Fixed

- SCPI socket connection fallback to VXI-11.
- E5071C directory catalog parsing for existing folders with trailing slashes.
- SCPI error queue draining so stale errors do not affect later operations.
- Screen capture transfer using `:MMEM:TRAN?` instead of an unterminated query.

## [0.3.0]

### Added

- Windows packaging and final application icon assets.

## [0.2.0]

### Added

- Measurement setup, calibration, state, and Auto Port Extension workflows.

[Unreleased]: https://github.com/TomatoET/SmithPilot/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/TomatoET/SmithPilot/releases/tag/v0.4.0
[0.3.0]: https://github.com/TomatoET/SmithPilot/releases/tag/v0.3
[0.2.0]: https://github.com/TomatoET/SmithPilot/releases/tag/v0.2
