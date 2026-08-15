"""Einheitliche, nutzerfreundliche Fehler für optionale Laufzeitdienste."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StudioError(RuntimeError):
    """A recoverable error with an actionable explanation for the UI."""

    code: str
    message: str
    remedy: str = ""

    def __str__(self) -> str:
        return self.message if not self.remedy else f"{self.message} {self.remedy}"


class DependencyUnavailableError(StudioError):
    pass


class ProviderUnavailableError(StudioError):
    pass
