from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrintAdapterDecision:
    event: str
    outcome: str
    severity: str
    retryable: bool
    side_effect_state: str
    reason_code: str | None = None
    metadata: dict[str, object] | None = None


class PrintAdapter:
    target_id = "printer"
    confirmed_status_message = "Order accepted. Print confirmed."
    needs_human_status_message = "Order accepted. Printer issue detected. Human attention required."
    alerted_status_message = "Order accepted. Printer issue detected. Operator alerted by email. Human attention required."
    alert_failed_status_message = "Order accepted. Printer issue detected. Email alert failed. Human attention required."

    def decide(self, configured_mode: str) -> PrintAdapterDecision:
        raise NotImplementedError


class PrinterAdapter(PrintAdapter):
    target_id = "printer"

    def decide(self, configured_mode: str) -> PrintAdapterDecision:
        if configured_mode == "printer_offline":
            return PrintAdapterDecision(
                event="PRINTER_OFFLINE",
                outcome="UNAVAILABLE",
                reason_code="PRINTER_OFFLINE",
                severity="high",
                retryable=True,
                side_effect_state="none",
            )
        if configured_mode == "paper_out":
            return PrintAdapterDecision(
                event="PAPER_OUT",
                outcome="FAILED_PERMANENT",
                reason_code="PAPER_OUT",
                severity="high",
                retryable=False,
                side_effect_state="none",
            )
        if configured_mode == "timeout":
            return PrintAdapterDecision(
                event="PRINT_TIMEOUT",
                outcome="TIMEOUT_UNKNOWN",
                reason_code="USB_TIMEOUT",
                severity="high",
                retryable=True,
                side_effect_state="unknown",
            )
        if configured_mode == "uncertain":
            return PrintAdapterDecision(
                event="PRINT_UNCERTAIN",
                outcome="TIMEOUT_UNKNOWN",
                reason_code="PRINT_STATE_UNCERTAIN",
                severity="high",
                retryable=False,
                side_effect_state="unknown",
            )
        if configured_mode == "precheck_failed":
            return PrintAdapterDecision(
                event="PRINT_FAILED_PRECHECK",
                outcome="FAILED_PERMANENT",
                reason_code="PRECHECK_FAILED",
                severity="high",
                retryable=False,
                side_effect_state="none",
            )
        return PrintAdapterDecision(
            event="PRINT_SUCCESS_CONFIRMED",
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
        )


class ScreenAdapter(PrintAdapter):
    target_id = "screen"
    confirmed_status_message = "Order accepted. Operator screen confirmed."
    needs_human_status_message = "Order accepted. Screen surface issue detected. Human attention required."
    alerted_status_message = "Order accepted. Screen surface issue detected. Operator alerted by email. Human attention required."
    alert_failed_status_message = "Order accepted. Screen surface issue detected. Email alert failed. Human attention required."

    def decide(self, configured_mode: str) -> PrintAdapterDecision:
        if configured_mode in {"screen_offline", "printer_offline", "unavailable"}:
            return PrintAdapterDecision(
                event="PRINT_FAILED_PRECHECK",
                outcome="UNAVAILABLE",
                reason_code="SCREEN_UNAVAILABLE",
                severity="high",
                retryable=True,
                side_effect_state="none",
            )
        if configured_mode == "timeout":
            return PrintAdapterDecision(
                event="PRINT_TIMEOUT",
                outcome="TIMEOUT_UNKNOWN",
                reason_code="SCREEN_TIMEOUT",
                severity="high",
                retryable=True,
                side_effect_state="unknown",
            )
        if configured_mode == "uncertain":
            return PrintAdapterDecision(
                event="PRINT_UNCERTAIN",
                outcome="TIMEOUT_UNKNOWN",
                reason_code="SCREEN_STATE_UNCERTAIN",
                severity="high",
                retryable=False,
                side_effect_state="unknown",
            )
        return PrintAdapterDecision(
            event="PRINT_SUCCESS_CONFIRMED",
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={"delivery_surface": "screen"},
        )


def build_print_adapter(target: str) -> PrintAdapter:
    normalized = target.strip().lower()
    if normalized == "screen":
        return ScreenAdapter()
    return PrinterAdapter()


__all__ = [
    "PrintAdapter",
    "PrintAdapterDecision",
    "build_print_adapter",
]
