from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    kind: str
    message: str

    @classmethod
    def now(cls, kind: str, message: str) -> "LogEntry":
        return cls(timestamp=datetime.now(), kind=kind, message=message)


def format_log_entry(entry: LogEntry) -> str:
    time_text = entry.timestamp.strftime("%H:%M:%S")
    kind = entry.kind.upper()
    return f"{time_text} {kind:<10} {entry.message}"
