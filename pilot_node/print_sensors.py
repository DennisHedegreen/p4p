from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrintSensorObservation:
    state: str
    metadata: dict[str, object]


class PrintSensor:
    source_id = "simulated"

    def precheck(self) -> PrintSensorObservation:
        raise NotImplementedError

    def postcheck(self) -> PrintSensorObservation:
        raise NotImplementedError


class SimulatedPrintSensor(PrintSensor):
    source_id = "simulated"

    def __init__(self, *, precheck_state: str, postcheck_state: str) -> None:
        self._precheck_state = normalize_sensor_state(precheck_state, default="ok")
        self._postcheck_state = normalize_sensor_state(postcheck_state, default="confirmed")

    def precheck(self) -> PrintSensorObservation:
        return PrintSensorObservation(
            state=self._precheck_state,
            metadata={"sensor_source": self.source_id},
        )

    def postcheck(self) -> PrintSensorObservation:
        return PrintSensorObservation(
            state=self._postcheck_state,
            metadata={"sensor_source": self.source_id},
        )


class StatusFilePrintSensor(PrintSensor):
    source_id = "status_file"

    def __init__(self, *, status_path: str, precheck_state: str, postcheck_state: str) -> None:
        self._status_path = status_path.strip()
        self._fallback_precheck = normalize_sensor_state(precheck_state, default="ok")
        self._fallback_postcheck = normalize_sensor_state(postcheck_state, default="confirmed")

    def precheck(self) -> PrintSensorObservation:
        payload = self._read_payload()
        return PrintSensorObservation(
            state=normalize_sensor_state(str(payload.get("precheck", self._fallback_precheck)), default="ok"),
            metadata={
                "sensor_source": self.source_id,
                "sensor_status_path": self._status_path,
            },
        )

    def postcheck(self) -> PrintSensorObservation:
        payload = self._read_payload()
        return PrintSensorObservation(
            state=normalize_sensor_state(str(payload.get("postcheck", self._fallback_postcheck)), default="confirmed"),
            metadata={
                "sensor_source": self.source_id,
                "sensor_status_path": self._status_path,
            },
        )

    def _read_payload(self) -> dict[str, object]:
        if not self._status_path:
            return {}
        path = Path(self._status_path)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


class SerialStatusPrintSensor(PrintSensor):
    source_id = "serial_status"

    def __init__(self, *, serial_path: str, precheck_state: str, postcheck_state: str) -> None:
        self._serial_path = serial_path.strip()
        self._fallback_precheck = normalize_sensor_state(precheck_state, default="ok")
        self._fallback_postcheck = normalize_sensor_state(postcheck_state, default="confirmed")

    def precheck(self) -> PrintSensorObservation:
        state, raw_line = self._read_phase("precheck", fallback=self._fallback_precheck)
        return PrintSensorObservation(
            state=state,
            metadata={
                "sensor_source": self.source_id,
                "sensor_serial_path": self._serial_path,
                "sensor_raw_line": raw_line,
            },
        )

    def postcheck(self) -> PrintSensorObservation:
        state, raw_line = self._read_phase("postcheck", fallback=self._fallback_postcheck)
        return PrintSensorObservation(
            state=state,
            metadata={
                "sensor_source": self.source_id,
                "sensor_serial_path": self._serial_path,
                "sensor_raw_line": raw_line,
            },
        )

    def _read_phase(self, phase: str, *, fallback: str) -> tuple[str, str | None]:
        if not self._serial_path:
            return fallback, None
        path = Path(self._serial_path)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return fallback, None

        matched_line: str | None = None
        matched_state: str | None = None
        for raw_line in lines:
            candidate = raw_line.strip()
            if not candidate:
                continue
            parsed = parse_serial_status_line(candidate)
            if parsed is None:
                continue
            candidate_phase, candidate_state = parsed
            if candidate_phase == phase:
                matched_line = candidate
                matched_state = candidate_state
        if matched_state is None:
            return fallback, None
        return normalize_sensor_state(matched_state, default=fallback), matched_line


def normalize_sensor_state(value: str, *, default: str) -> str:
    normalized = value.strip().lower()
    return normalized or default


def parse_serial_status_line(line: str) -> tuple[str, str] | None:
    for delimiter in (":", "="):
        if delimiter not in line:
            continue
        phase, state = line.split(delimiter, 1)
        normalized_phase = phase.strip().lower()
        normalized_state = state.strip().lower()
        if normalized_phase in {"precheck", "postcheck"} and normalized_state:
            return normalized_phase, normalized_state
    return None


def build_print_sensor(
    *,
    source: str,
    status_path: str,
    serial_path: str,
    precheck_state: str,
    postcheck_state: str,
) -> PrintSensor:
    normalized = source.strip().lower()
    if normalized == "status_file":
        return StatusFilePrintSensor(
            status_path=status_path,
            precheck_state=precheck_state,
            postcheck_state=postcheck_state,
        )
    if normalized == "serial_status":
        return SerialStatusPrintSensor(
            serial_path=serial_path,
            precheck_state=precheck_state,
            postcheck_state=postcheck_state,
        )
    return SimulatedPrintSensor(precheck_state=precheck_state, postcheck_state=postcheck_state)


__all__ = [
    "PrintSensor",
    "PrintSensorObservation",
    "build_print_sensor",
]
