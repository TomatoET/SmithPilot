from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

LogCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class InstrumentIdentity:
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    firmware: str = ""

    @classmethod
    def from_idn(cls, response: str) -> InstrumentIdentity:
        parts = [part.strip() for part in response.strip().split(",")]
        padded = (parts + ["", "", "", ""])[:4]
        return cls(
            manufacturer=padded[0],
            model=padded[1],
            serial_number=padded[2],
            firmware=padded[3],
        )


class InstrumentError(Exception):
    """Base exception for instrument operations."""


class InstrumentConnectionError(InstrumentError):
    """Raised when the instrument cannot be reached or the link is lost."""


class InstrumentTimeoutError(InstrumentConnectionError):
    """Raised when the instrument does not answer within the timeout."""


class InstrumentCommandError(InstrumentError):
    """Raised when a SCPI command is invalid or rejected."""


class InstrumentSafetyError(InstrumentCommandError):
    """Raised when a command is outside the V0.1 safety envelope."""


class BaseVNA(ABC):
    @abstractmethod
    def connect(self) -> InstrumentIdentity:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def query_idn(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def query_error(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def write(self, command: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def query(self, command: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def set_start_frequency(self, freq_hz: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_stop_frequency(self, freq_hz: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_sweep_points(self, points: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_start_frequency(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_stop_frequency(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_sweep_points(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def trigger_single_sweep(self) -> None:
        raise NotImplementedError
