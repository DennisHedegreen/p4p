from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from p4p_core import StoredOrder


@dataclass(frozen=True)
class PrintDriverResult:
    success: bool
    outcome: str
    severity: str
    retryable: bool
    side_effect_state: str
    reason_code: str | None = None
    metadata: dict[str, object] | None = None


class PrintDriver:
    driver_id = "simulated"

    def deliver(self, *, target_id: str, order: StoredOrder, action_id: str) -> PrintDriverResult:
        raise NotImplementedError


class SimulatedPrintDriver(PrintDriver):
    driver_id = "simulated"

    def deliver(self, *, target_id: str, order: StoredOrder, action_id: str) -> PrintDriverResult:
        return PrintDriverResult(
            success=True,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={"print_driver": self.driver_id, "delivery_target": target_id},
        )


class FileSpoolPrintDriver(PrintDriver):
    driver_id = "file_spool"

    def __init__(self, spool_dir: str) -> None:
        self._spool_dir = spool_dir.strip()

    def deliver(self, *, target_id: str, order: StoredOrder, action_id: str) -> PrintDriverResult:
        if not self._spool_dir:
            return PrintDriverResult(
                success=False,
                outcome="FAILED_PERMANENT",
                severity="high",
                retryable=False,
                side_effect_state="none",
                reason_code="SPOOL_DIR_NOT_CONFIGURED",
                metadata={"print_driver": self.driver_id, "delivery_target": target_id},
            )

        spool_path = Path(self._spool_dir)
        ticket_path = spool_path / f"{order.order_id}.txt"
        try:
            spool_path.mkdir(parents=True, exist_ok=True)
            reused = ticket_path.exists()
            if not reused:
                ticket_path.write_text(render_ticket(target_id=target_id, order=order, action_id=action_id), encoding="utf-8")
        except OSError:
            return PrintDriverResult(
                success=False,
                outcome="FAILED_RETRYABLE",
                severity="high",
                retryable=True,
                side_effect_state="none",
                reason_code="SPOOL_WRITE_FAILED",
                metadata={
                    "print_driver": self.driver_id,
                    "delivery_target": target_id,
                    "spool_path": str(ticket_path),
                },
            )

        return PrintDriverResult(
            success=True,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={
                "print_driver": self.driver_id,
                "delivery_target": target_id,
                "spool_path": str(ticket_path),
                "spool_reused": reused,
            },
        )


class DevicePathPrintDriver(PrintDriver):
    driver_id = "device_path"

    def __init__(self, device_path: str) -> None:
        self._device_path = device_path.strip()

    def deliver(self, *, target_id: str, order: StoredOrder, action_id: str) -> PrintDriverResult:
        if not self._device_path:
            return PrintDriverResult(
                success=False,
                outcome="FAILED_PERMANENT",
                severity="high",
                retryable=False,
                side_effect_state="none",
                reason_code="DEVICE_PATH_NOT_CONFIGURED",
                metadata={"print_driver": self.driver_id, "delivery_target": target_id},
            )

        device_path = Path(self._device_path)
        payload = render_ticket(target_id=target_id, order=order, action_id=action_id).encode("utf-8") + b"\n\n"
        try:
            device_path.parent.mkdir(parents=True, exist_ok=True)
            with device_path.open("ab") as handle:
                written = handle.write(payload)
        except OSError:
            return PrintDriverResult(
                success=False,
                outcome="FAILED_RETRYABLE",
                severity="high",
                retryable=True,
                side_effect_state="none",
                reason_code="DEVICE_WRITE_FAILED",
                metadata={
                    "print_driver": self.driver_id,
                    "delivery_target": target_id,
                    "device_path": str(device_path),
                },
            )

        return PrintDriverResult(
            success=True,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={
                "print_driver": self.driver_id,
                "delivery_target": target_id,
                "device_path": str(device_path),
                "bytes_written": written,
            },
        )


class EscPosRawPrintDriver(PrintDriver):
    driver_id = "escpos_raw"

    def __init__(self, device_path: str, *, cut_mode: str) -> None:
        self._device_path = device_path.strip()
        self._cut_mode = normalize_cut_mode(cut_mode)

    def deliver(self, *, target_id: str, order: StoredOrder, action_id: str) -> PrintDriverResult:
        if not self._device_path:
            return PrintDriverResult(
                success=False,
                outcome="FAILED_PERMANENT",
                severity="high",
                retryable=False,
                side_effect_state="none",
                reason_code="DEVICE_PATH_NOT_CONFIGURED",
                metadata={"print_driver": self.driver_id, "delivery_target": target_id},
            )

        device_path = Path(self._device_path)
        payload = render_escpos_ticket(target_id=target_id, order=order, action_id=action_id, cut_mode=self._cut_mode)
        try:
            device_path.parent.mkdir(parents=True, exist_ok=True)
            with device_path.open("ab") as handle:
                written = handle.write(payload)
        except OSError:
            return PrintDriverResult(
                success=False,
                outcome="FAILED_RETRYABLE",
                severity="high",
                retryable=True,
                side_effect_state="none",
                reason_code="DEVICE_WRITE_FAILED",
                metadata={
                    "print_driver": self.driver_id,
                    "delivery_target": target_id,
                    "device_path": str(device_path),
                    "cut_mode": self._cut_mode,
                },
            )

        return PrintDriverResult(
            success=True,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={
                "print_driver": self.driver_id,
                "delivery_target": target_id,
                "device_path": str(device_path),
                "bytes_written": written,
                "cut_mode": self._cut_mode,
                "encoding": "ascii_replace",
            },
        )


def render_ticket(*, target_id: str, order: StoredOrder, action_id: str) -> str:
    item_lines = [f"- {item.quantity}x {item.id}" for item in order.items]
    return "\n".join(
        [
            f"P4P operator ticket ({target_id})",
            f"action_id: {action_id}",
            f"order_id: {order.order_id}",
            f"customer_name: {order.customer_name}",
            f"customer_contact: {order.customer_contact}",
            f"fulfillment: {order.fulfillment}",
            "items:",
            *item_lines,
            f"note: {order.note or '-'}",
            f"requested_at: {order.requested_at.isoformat()}",
        ]
    )


def render_escpos_ticket(*, target_id: str, order: StoredOrder, action_id: str, cut_mode: str) -> bytes:
    text = render_ticket(target_id=target_id, order=order, action_id=action_id)
    payload = bytearray()
    payload.extend(b"\x1b@")
    payload.extend(text.encode("ascii", errors="replace"))
    payload.extend(b"\n\n\n")
    if cut_mode == "full":
        payload.extend(b"\x1dV\x00")
    elif cut_mode == "partial":
        payload.extend(b"\x1dV\x01")
    return bytes(payload)


def normalize_cut_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"full", "partial", "none"}:
        return normalized
    return "partial"


def build_print_driver(driver_id: str, spool_dir: str, device_path: str, escpos_cut_mode: str) -> PrintDriver:
    normalized = driver_id.strip().lower()
    if normalized == "file_spool":
        return FileSpoolPrintDriver(spool_dir)
    if normalized == "device_path":
        return DevicePathPrintDriver(device_path)
    if normalized == "escpos_raw":
        return EscPosRawPrintDriver(device_path, cut_mode=escpos_cut_mode)
    return SimulatedPrintDriver()


__all__ = [
    "PrintDriver",
    "PrintDriverResult",
    "build_print_driver",
]
