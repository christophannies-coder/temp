"""Central configuration loading with conservative defaults and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class ConfigurationError(ValueError):
    """Raised when a user-editable settings file cannot be used safely."""


@dataclass(frozen=True)
class ApplicationConfig:
    """Validated application settings independent of a concrete provider.

    Unknown keys are retained so existing `settings.json` files stay forwards
    and backwards compatible during the gradual migration.
    """

    values: Mapping[str, Any] = field(default_factory=dict)
    source: Path | None = None

    @classmethod
    def load(cls, path: Path, defaults: Mapping[str, Any] | None = None) -> "ApplicationConfig":
        merged: dict[str, Any] = dict(defaults or {})
        if not path.exists():
            return cls(merged, path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigurationError(f"Konfiguration kann nicht gelesen werden: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Konfiguration enthält ungültiges JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("Die Konfiguration muss ein JSON-Objekt sein.")
        merged.update(payload)
        return cls(merged, path)

    def get_str(self, key: str, default: str = "") -> str:
        value = self.values.get(key, default)
        return default if value is None else str(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.values.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise ConfigurationError(f"'{key}' muss wahr oder falsch sein.")

    def get_int(self, key: str, default: int = 0, *, minimum: int | None = None) -> int:
        value = self.values.get(key, default)
        if isinstance(value, bool):
            raise ConfigurationError(f"'{key}' muss eine ganze Zahl sein.")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"'{key}' muss eine ganze Zahl sein.") from exc
        if minimum is not None and result < minimum:
            raise ConfigurationError(f"'{key}' muss mindestens {minimum} sein.")
        return result


    def save(self) -> None:
        """Write JSON atomically, keeping keys not yet known to the current UI."""
        if self.source is None:
            raise ConfigurationError("Für diese Konfiguration wurde kein Speicherort angegeben.")
        self.source.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.source.with_suffix(self.source.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(dict(self.values), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.source)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ConfigurationError(f"Konfiguration kann nicht gespeichert werden: {self.source}") from exc
