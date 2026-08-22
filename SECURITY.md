# Security Policy

## Supported Versions

Security fixes are applied to the latest released version.

| Version | Supported |
| --- | --- |
| 0.4.x | Yes |
| Earlier versions | No |

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's
[private vulnerability reporting](https://github.com/TomatoET/SmithPilot/security/advisories/new)
and include:

- Affected version or commit
- Reproduction steps
- Expected impact
- Whether real instrument hardware is required

Please avoid sending destructive SCPI commands or testing against equipment you
do not own or have permission to use. Reports will be acknowledged through the
GitHub advisory and assessed before public disclosure.

## Operational Safety

SmithPilot can change analyzer configuration, calibration, state files, and
instrument storage. Treat unauthorized command execution, path validation
bypass, unsafe state overwrite, and unbounded file transfer as security issues.
