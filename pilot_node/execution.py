from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from p4p_core import (
    CONTRACT_PHASE_METADATA_KEY,
    ModuleManifest,
    ModuleResultEvent,
    OrderStatusUpdate,
    StoredOrder,
    TRIGGER_EVENT_METADATA_KEY,
    utc_now,
    validate_pilot_order_event_flow,
)

from pilot_node.print_adapters import build_print_adapter
from pilot_node.print_drivers import build_print_driver
from pilot_node.print_sensors import build_print_sensor
from pilot_node.runtime import PilotRuntime, effective_flow_module_ids, effective_payment_module_id


ORDER_RECEIVER_MODULE_ID = "p4p.order.receiver"
CATALOG_EDITOR_MODULE_ID = "p4p.catalog.editor"
CUSTOMER_STATUS_MODULE_ID = "p4p.customer.status"
KITCHEN_SCREEN_MODULE_ID = "p4p.kitchen.screen"
MENU_LIST_MODULE_ID = "p4p.menu.list"
PRINT_MODULE_ID = "p4p.order.print"
NOTIFY_EMAIL_MODULE_ID = "p4p.notify.email"
STOCK_BASIC_MODULE_ID = "p4p.stock.basic"
PAYMENT_CASH_MODULE_ID = "p4p.payment.cash"
GODPAY_MOCK_MODULE_ID = "p4p.payment.godpay-mock"
CHAOSPAY_MOCK_MODULE_ID = "p4p.payment.chaospay-mock"
INTERNAL_RUNTIME_MODULE_IDS = frozenset({ORDER_RECEIVER_MODULE_ID})
REQUEST_PHASE = "request"
RESULT_PHASE = "result"
PAYMENT_RESULT_EVENTS = frozenset({"PAYMENT_MODE_CHANGED", "PAYMENT_FAILED"})
PAYMENT_SUCCESS_OUTCOMES = frozenset({"SUCCESS"})
PAYMENT_FAILURE_OUTCOMES = frozenset({"FAILED_RETRYABLE", "FAILED_PERMANENT", "UNAVAILABLE", "TIMEOUT_UNKNOWN"})
SIDE_EFFECT_STATES = frozenset({"none", "confirmed", "unknown"})


@dataclass(frozen=True)
class ModuleExecutor:
    module_id: str
    lane: str
    execute: Callable[[PilotRuntime, StoredOrder], tuple[StoredOrder, bool]]


def module_enabled(runtime: PilotRuntime, module_id: str) -> bool:
    return runtime.config.resolved_modules.contains(module_id)


def _resolved_runtime_manifest(runtime: PilotRuntime, module_id: str) -> ModuleManifest | None:
    manifest = runtime.config.resolved_modules.get(module_id)
    if manifest is not None:
        return manifest
    if module_id in INTERNAL_RUNTIME_MODULE_IDS:
        return None
    raise ValueError(f"Unknown runtime module id: {module_id}")


def module_metadata(runtime: PilotRuntime, module_id: str) -> dict[str, object]:
    manifest = _resolved_runtime_manifest(runtime, module_id)
    if manifest is None:
        return {}
    return {
        "module_provider": manifest.provider_id,
        "module_lane": manifest.lane,
        "module_visibility": manifest.visibility,
        "module_blocking_policy": manifest.blocking_policy,
        "module_readiness": manifest.readiness,
    }


def module_supports_fallback(runtime: PilotRuntime, module_id: str, event_name: str, fallback_module_id: str) -> bool:
    manifest = _resolved_runtime_manifest(runtime, module_id)
    fallback_manifest = _resolved_runtime_manifest(runtime, fallback_module_id)
    if manifest is None or fallback_manifest is None:
        return False
    return fallback_module_id in manifest.fallbacks_for(event_name) and fallback_manifest.accepts_event(event_name)


def assert_module_event_contract(
    runtime: PilotRuntime,
    *,
    module_id: str,
    event_name: str,
    outcome: str,
    contract_phase: str,
) -> None:
    manifest = _resolved_runtime_manifest(runtime, module_id)
    if manifest is None:
        return
    if contract_phase == REQUEST_PHASE:
        if not manifest.accepts_event(event_name):
            raise ValueError(f"Module {module_id} request event {event_name} is not declared in input_events")
        return
    if not manifest.emits_event(event_name):
        raise ValueError(f"Module {module_id} result event {event_name} is not declared in output_events")
    if outcome != "SUCCESS" and not manifest.declares_failure_mode(event_name):
        raise ValueError(f"Module {module_id} result event {event_name} is missing from failure_modes")


def build_hardware_profile_metadata(runtime: PilotRuntime) -> dict[str, object]:
    return {
        "hardware_profile": runtime.config.hardware_profile,
        "hardware_profile_customized": runtime.config.hardware_profile_customized,
    }


def _build_event_metadata(
    contract_phase: str,
    metadata: dict[str, object] | None,
    *,
    trigger_event: str | None = None,
) -> dict[str, object]:
    merged = dict(metadata or {})
    if CONTRACT_PHASE_METADATA_KEY in merged:
        raise ValueError(f"{CONTRACT_PHASE_METADATA_KEY} is reserved event metadata")
    if trigger_event is not None:
        normalized_trigger_event = trigger_event.strip()
        if not normalized_trigger_event:
            raise ValueError(f"{TRIGGER_EVENT_METADATA_KEY} must not be blank")
        existing_trigger_event = merged.get(TRIGGER_EVENT_METADATA_KEY)
        if existing_trigger_event is not None:
            if not isinstance(existing_trigger_event, str) or existing_trigger_event.strip() != normalized_trigger_event:
                raise ValueError(
                    f"{TRIGGER_EVENT_METADATA_KEY} metadata must match explicit trigger_event"
                )
        merged[TRIGGER_EVENT_METADATA_KEY] = normalized_trigger_event
    merged[CONTRACT_PHASE_METADATA_KEY] = contract_phase
    return merged


def build_result_event(
    *,
    runtime: PilotRuntime,
    event: str,
    source_module: str,
    order: StoredOrder,
    action_id: str,
    idempotency_key: str,
    outcome: str,
    severity: str,
    retryable: bool,
    side_effect_state: str,
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
    contract_phase: str = RESULT_PHASE,
    trigger_event: str | None = None,
) -> ModuleResultEvent:
    assert_module_event_contract(
        runtime,
        module_id=source_module,
        event_name=event,
        outcome=outcome,
        contract_phase=contract_phase,
    )
    return ModuleResultEvent(
        event=event,
        source_module=source_module,
        order_id=order.order_id,
        action_id=action_id,
        idempotency_key=idempotency_key,
        outcome=outcome,
        reason_code=reason_code,
        severity=severity,
        retryable=retryable,
        side_effect_state=side_effect_state,
        timestamp=utc_now(),
        metadata=_build_event_metadata(contract_phase, metadata, trigger_event=trigger_event),
    )


def record_order_flow_event(runtime: PilotRuntime, event: ModuleResultEvent) -> ModuleResultEvent:
    existing_events = runtime.store.list_order_events(event.order_id or "")
    validate_pilot_order_event_flow(
        existing_events,
        event,
        enabled_module_ids=effective_flow_module_ids(runtime),
        module_manifests=runtime.config.resolved_modules.manifests,
    )
    return runtime.store.record_order_event(event)


def process_accepted_order(runtime: PilotRuntime, order: StoredOrder) -> StoredOrder:
    accepted_order = runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(status="accepted", status_message="Order accepted by node runtime."),
    )
    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="ORDER_ACCEPTED",
            source_module=ORDER_RECEIVER_MODULE_ID,
            order=accepted_order,
            action_id=f"order:{accepted_order.order_id}:accept",
            idempotency_key=f"order:{accepted_order.order_id}:accept",
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={"order_mode": runtime.store.get_state("order_mode", runtime.config.node_order_mode_default)},
        )
    )
    if module_enabled(runtime, STOCK_BASIC_MODULE_ID):
        accepted_order, stock_allows_next_step = execute_stock_lane(runtime, accepted_order)
        if not stock_allows_next_step:
            return accepted_order
    accepted_order, payment_allows_next_step = execute_module_lane(runtime, accepted_order, lane="payment")
    if not payment_allows_next_step:
        return accepted_order
    if not module_enabled(runtime, PRINT_MODULE_ID):
        return accepted_order
    return execute_print_lane(runtime, accepted_order)


def execute_stock_lane(runtime: PilotRuntime, order: StoredOrder) -> tuple[StoredOrder, bool]:
    stock_action_id = f"order:{order.order_id}:stock:basic"
    stock_idempotency_key = f"stock:{order.order_id}:basic"
    requested_item_ids = tuple(item.id for item in order.items)
    unavailable_item_id_set = set(runtime.config.stock_unavailable_item_ids)
    unavailable_item_ids = tuple(
        item_id for item_id in requested_item_ids if item_id in unavailable_item_id_set
    )
    configured_mode = runtime.config.stock_module_mode.strip().lower()
    stock_metadata = {
        **module_metadata(runtime, STOCK_BASIC_MODULE_ID),
        "configured_mode": configured_mode or "validated",
        "requested_item_ids": list(requested_item_ids),
        "unavailable_item_ids": list(unavailable_item_ids),
    }

    if unavailable_item_ids or configured_mode in {"item_not_possible", "unavailable", "failed"}:
        blocked_item_ids = unavailable_item_ids or requested_item_ids[:1]
        record_order_flow_event(
            runtime,
            build_result_event(
                runtime=runtime,
                event="ITEM_NOT_POSSIBLE",
                source_module=STOCK_BASIC_MODULE_ID,
                order=order,
                action_id=stock_action_id,
                idempotency_key=stock_idempotency_key,
                outcome="FAILED_PERMANENT",
                reason_code="ITEM_NOT_POSSIBLE",
                severity="high",
                retryable=False,
                side_effect_state="none",
                trigger_event="ORDER_ACCEPTED",
                metadata={**stock_metadata, "blocked_item_ids": list(blocked_item_ids)},
            ),
        )
        record_order_flow_event(
            runtime,
            build_result_event(
                runtime=runtime,
                event="ORDER_NEEDS_HUMAN",
                source_module=ORDER_RECEIVER_MODULE_ID,
                order=order,
                action_id=f"order:{order.order_id}:needs-human:stock",
                idempotency_key=f"human:{order.order_id}:stock",
                outcome="NEEDS_HUMAN",
                severity="high",
                retryable=False,
                side_effect_state="none",
                trigger_event="ITEM_NOT_POSSIBLE",
                metadata={**stock_metadata, "blocked_item_ids": list(blocked_item_ids)},
            ),
        )
        updated_order = runtime.store.update_order_status(
            order.order_id,
            OrderStatusUpdate(
                status="accepted",
                status_message="Order accepted. Stock check needs human attention.",
            ),
        )
        return updated_order, False

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="ORDER_VALIDATED",
            source_module=STOCK_BASIC_MODULE_ID,
            order=order,
            action_id=stock_action_id,
            idempotency_key=stock_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            trigger_event="ORDER_ACCEPTED",
            metadata=stock_metadata,
        ),
    )
    updated_order = runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(status="accepted", status_message="Order accepted. Stock validated."),
    )
    return updated_order, True


def execute_payment_cash_module(runtime: PilotRuntime, order: StoredOrder) -> tuple[StoredOrder, bool]:
    payment_action_id = f"order:{order.order_id}:payment:cash"
    payment_idempotency_key = f"payment:{order.order_id}:cash"
    configured_mode = runtime.config.payment_cash_mode.strip().lower()
    payment_metadata = {
        **module_metadata(runtime, PAYMENT_CASH_MODULE_ID),
        "configured_mode": configured_mode or "pay_at_pickup",
        "payment_method": "pay_at_pickup",
        "payment_scope": "outside_protocol",
    }

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_REQUIRED",
            source_module=PAYMENT_CASH_MODULE_ID,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            contract_phase=REQUEST_PHASE,
            metadata=payment_metadata,
        ),
    )

    if configured_mode in {"failed", "unavailable", "payment_failed"}:
        record_order_flow_event(
            runtime,
            build_result_event(
                runtime=runtime,
                event="PAYMENT_FAILED",
                source_module=PAYMENT_CASH_MODULE_ID,
                order=order,
                action_id=payment_action_id,
                idempotency_key=payment_idempotency_key,
                outcome="UNAVAILABLE",
                reason_code="PAYMENT_MODE_UNAVAILABLE",
                severity="high",
                retryable=False,
                side_effect_state="none",
                trigger_event="PAYMENT_REQUIRED",
                metadata=payment_metadata,
            ),
        )
        record_order_flow_event(
            runtime,
            build_result_event(
                runtime=runtime,
                event="ORDER_NEEDS_HUMAN",
                source_module=ORDER_RECEIVER_MODULE_ID,
                order=order,
                action_id=f"order:{order.order_id}:needs-human:payment",
                idempotency_key=f"human:{order.order_id}:payment",
                outcome="NEEDS_HUMAN",
                severity="high",
                retryable=False,
                side_effect_state="none",
                trigger_event="PAYMENT_FAILED",
                metadata=payment_metadata,
            ),
        )
        updated_order = runtime.store.update_order_status(
            order.order_id,
            OrderStatusUpdate(
                status="accepted",
                status_message="Order accepted. Payment mode needs human attention.",
            ),
        )
        return updated_order, False

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_MODE_CHANGED",
            source_module=PAYMENT_CASH_MODULE_ID,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            trigger_event="PAYMENT_REQUIRED",
            metadata=payment_metadata,
        ),
    )
    updated_order = runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(status="accepted", status_message="Order accepted. Payment set to pay at pickup."),
    )
    return updated_order, True


def _godpay_roll(runtime: PilotRuntime, order: StoredOrder) -> int:
    if runtime.config.godpay_force_roll is not None:
        return runtime.config.godpay_force_roll
    seed = runtime.config.godpay_seed
    if seed:
        digest = hashlib.sha256(f"{seed}:{order.order_id}".encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % 100 + 1
    return secrets.randbelow(100) + 1


def execute_godpay_mock_module(runtime: PilotRuntime, order: StoredOrder) -> tuple[StoredOrder, bool]:
    payment_action_id = f"order:{order.order_id}:payment:godpay-mock"
    payment_idempotency_key = f"payment:{order.order_id}:godpay-mock"
    amount = _order_amount(runtime, order)
    threshold = runtime.config.godpay_success_threshold
    roll = _godpay_roll(runtime, order)
    accepted = roll <= threshold
    result_message = (
        "The pizza gods accepted the offering."
        if accepted
        else "The pizza gods declined this order."
    )
    payment_metadata = {
        **module_metadata(runtime, GODPAY_MOCK_MODULE_ID),
        "payment_scope": "internal_mock",
        "payment_method": "godpay_mock",
        "mock_module": True,
        "real_payment": False,
        "settlement": "none",
        "amount": amount,
        "currency": "TEST",
        "roll": roll,
        "success_threshold": threshold,
        "message": result_message,
    }

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_REQUIRED",
            source_module=GODPAY_MOCK_MODULE_ID,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            contract_phase=REQUEST_PHASE,
            metadata=payment_metadata,
        ),
    )

    if accepted:
        record_order_flow_event(
            runtime,
            build_result_event(
                runtime=runtime,
                event="PAYMENT_MODE_CHANGED",
                source_module=GODPAY_MOCK_MODULE_ID,
                order=order,
                action_id=payment_action_id,
                idempotency_key=payment_idempotency_key,
                outcome="SUCCESS",
                severity="low",
                retryable=False,
                side_effect_state="confirmed",
                trigger_event="PAYMENT_REQUIRED",
                metadata=payment_metadata,
            ),
        )
        runtime.store.update_order_payment_method(order.order_id, "godpay_mock")
        updated_order = runtime.store.update_order_status(
            order.order_id,
            OrderStatusUpdate(status="accepted", status_message=result_message),
        )
        return updated_order, True

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_FAILED",
            source_module=GODPAY_MOCK_MODULE_ID,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome="FAILED_PERMANENT",
            reason_code="GODPAY_DECLINED",
            severity="high",
            retryable=True,
            side_effect_state="none",
            trigger_event="PAYMENT_REQUIRED",
            metadata=payment_metadata,
        ),
    )
    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="ORDER_NEEDS_HUMAN",
            source_module=ORDER_RECEIVER_MODULE_ID,
            order=order,
            action_id=f"order:{order.order_id}:needs-human:payment",
            idempotency_key=f"human:{order.order_id}:payment",
            outcome="NEEDS_HUMAN",
            severity="high",
            retryable=False,
            side_effect_state="none",
            trigger_event="PAYMENT_FAILED",
            metadata=payment_metadata,
        ),
    )
    updated_order = runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(status="accepted", status_message=result_message),
    )
    return updated_order, False


def _is_payment_manifest(manifest: ModuleManifest) -> bool:
    module_class = str(manifest.raw.get("module_class") or manifest.raw.get("type") or "").strip()
    return (
        module_class == "payment"
        and "PAYMENT_REQUIRED" in manifest.input_events
        and PAYMENT_RESULT_EVENTS.issubset(set(manifest.output_events))
    )


def _external_payment_manifest(runtime: PilotRuntime, module_id: str) -> ModuleManifest | None:
    manifest = runtime.config.resolved_modules.get(module_id)
    if manifest is None or module_id == PAYMENT_CASH_MODULE_ID:
        return None
    raw_entrypoint = manifest.raw.get("entrypoint")
    if not isinstance(raw_entrypoint, str) or not raw_entrypoint.strip():
        return None
    if not _is_payment_manifest(manifest):
        return None
    return manifest


def _external_payment_url_error(url: str) -> str | None:
    if not url:
        return "PAYMENT_EXTERNAL_URL_MISSING"
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return "PAYMENT_EXTERNAL_URL_INVALID"
    if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return "PAYMENT_EXTERNAL_HTTP_NOT_LOOPBACK"
    return None


def _order_amount(runtime: PilotRuntime, order: StoredOrder) -> int:
    menu = runtime.store.menu()
    price_by_id = {item.id: item.price for item in menu.items}
    total = 0
    for item in order.items:
        total += price_by_id[item.id] * item.quantity
    return total


def _payment_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_event = payload.get("event")
    if isinstance(raw_event, dict):
        return raw_event
    status = str(payload.get("status") or "").strip().lower()
    if status == "confirmed":
        return {
            "event": "PAYMENT_MODE_CHANGED",
            "outcome": "SUCCESS",
            "side_effect_state": "confirmed",
        }
    return {
        "event": "PAYMENT_FAILED",
        "outcome": "FAILED_PERMANENT",
        "reason_code": "EXTERNAL_PAYMENT_NOT_CONFIRMED",
        "side_effect_state": "none",
    }


def _safe_payment_outcome(event_name: str, value: object) -> str:
    outcome = str(value or "").strip()
    allowed = PAYMENT_SUCCESS_OUTCOMES if event_name == "PAYMENT_MODE_CHANGED" else PAYMENT_FAILURE_OUTCOMES
    if outcome in allowed:
        return outcome
    return "SUCCESS" if event_name == "PAYMENT_MODE_CHANGED" else "FAILED_PERMANENT"


def _safe_side_effect_state(value: object, *, default: str) -> str:
    state = str(value or "").strip()
    return state if state in SIDE_EFFECT_STATES else default


def _record_external_payment_failure(
    runtime: PilotRuntime,
    order: StoredOrder,
    *,
    module_id: str,
    action_id: str,
    idempotency_key: str,
    reason_code: str,
    metadata: dict[str, object],
    outcome: str = "UNAVAILABLE",
    retryable: bool = True,
) -> tuple[StoredOrder, bool]:
    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_FAILED",
            source_module=module_id,
            order=order,
            action_id=action_id,
            idempotency_key=idempotency_key,
            outcome=outcome,
            reason_code=reason_code,
            severity="high",
            retryable=retryable,
            side_effect_state="none",
            trigger_event="PAYMENT_REQUIRED",
            metadata=metadata,
        ),
    )
    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="ORDER_NEEDS_HUMAN",
            source_module=ORDER_RECEIVER_MODULE_ID,
            order=order,
            action_id=f"order:{order.order_id}:needs-human:payment",
            idempotency_key=f"human:{order.order_id}:payment",
            outcome="NEEDS_HUMAN",
            severity="high",
            retryable=False,
            side_effect_state="none",
            trigger_event="PAYMENT_FAILED",
            metadata=metadata,
        ),
    )
    updated_order = runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(
            status="accepted",
            status_message="Order accepted. External payment needs human attention.",
        ),
    )
    return updated_order, False


def execute_unavailable_payment_module(runtime: PilotRuntime, order: StoredOrder) -> tuple[StoredOrder, bool]:
    module_id = effective_payment_module_id(runtime)
    if not module_id or not runtime.config.resolved_modules.contains(module_id):
        return order, True

    payment_action_id = f"order:{order.order_id}:payment:unavailable:{module_id}"
    payment_idempotency_key = f"payment:{order.order_id}:unavailable:{module_id}"
    payment_metadata = {
        **module_metadata(runtime, module_id),
        "payment_scope": "unavailable_payment_executor",
        "payment_module_id": module_id,
        "mock_module": module_id == CHAOSPAY_MOCK_MODULE_ID,
        "real_payment": False,
    }
    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_REQUIRED",
            source_module=module_id,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            contract_phase=REQUEST_PHASE,
            metadata=payment_metadata,
        ),
    )
    return _record_external_payment_failure(
        runtime,
        order,
        module_id=module_id,
        action_id=payment_action_id,
        idempotency_key=payment_idempotency_key,
        reason_code="PAYMENT_EXECUTOR_UNAVAILABLE",
        metadata=payment_metadata,
        outcome="UNAVAILABLE",
        retryable=False,
    )


def execute_external_payment_module(
    runtime: PilotRuntime,
    order: StoredOrder,
    *,
    module_id: str,
) -> tuple[StoredOrder, bool]:
    manifest = _external_payment_manifest(runtime, module_id)
    if manifest is None:
        return order, True

    payment_action_id = f"order:{order.order_id}:payment:external:{module_id}"
    payment_idempotency_key = f"payment:{order.order_id}:{module_id}"
    payment_url = runtime.config.payment_external_url or str(manifest.raw.get("entrypoint") or "").strip()
    amount = _order_amount(runtime, order)
    payment_metadata = {
        **module_metadata(runtime, module_id),
        "payment_scope": "external_test_module",
        "payment_entrypoint": payment_url,
        "payment_module_id": module_id,
        "merchant_id": runtime.config.payment_external_merchant_id,
        "currency": runtime.config.payment_external_currency,
        "amount": amount,
        "auto_confirm": runtime.config.payment_external_auto_confirm,
    }

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PAYMENT_REQUIRED",
            source_module=module_id,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            contract_phase=REQUEST_PHASE,
            metadata=payment_metadata,
        ),
    )

    url_error = _external_payment_url_error(payment_url)
    if url_error is not None:
        return _record_external_payment_failure(
            runtime,
            order,
            module_id=module_id,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            reason_code=url_error,
            metadata=payment_metadata,
            outcome="UNAVAILABLE",
            retryable=False,
        )
    if not runtime.config.payment_external_customer_user_id:
        return _record_external_payment_failure(
            runtime,
            order,
            module_id=module_id,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            reason_code="PAYMENT_CUSTOMER_USER_ID_MISSING",
            metadata=payment_metadata,
            outcome="FAILED_PERMANENT",
            retryable=False,
        )

    create_payload = {
        "order_id": order.order_id,
        "node_id": runtime.config.node_id,
        "merchant_id": runtime.config.payment_external_merchant_id,
        "customer_user_id": runtime.config.payment_external_customer_user_id,
        "amount": amount,
        "currency": runtime.config.payment_external_currency,
        "idempotency_key": payment_idempotency_key,
    }

    try:
        with httpx.Client(timeout=runtime.config.payment_external_timeout_seconds) as client:
            create_response = client.post(payment_url, json=create_payload)
            create_response.raise_for_status()
            payment_payload = create_response.json()
            if not isinstance(payment_payload, dict):
                return _record_external_payment_failure(
                    runtime,
                    order,
                    module_id=module_id,
                    action_id=payment_action_id,
                    idempotency_key=payment_idempotency_key,
                    reason_code="PAYMENT_EXTERNAL_RESPONSE_INVALID",
                    metadata=payment_metadata,
                    outcome="FAILED_PERMANENT",
                    retryable=False,
                )
            if runtime.config.payment_external_auto_confirm:
                payment_id = str(payment_payload.get("payment_id") or "").strip()
                if not payment_id:
                    return _record_external_payment_failure(
                        runtime,
                        order,
                        module_id=module_id,
                        action_id=payment_action_id,
                        idempotency_key=payment_idempotency_key,
                        reason_code="PAYMENT_EXTERNAL_ID_MISSING",
                        metadata=payment_metadata,
                        outcome="FAILED_PERMANENT",
                        retryable=False,
                    )
                confirm_url = f"{payment_url.rstrip('/')}/{payment_id}/confirm"
                confirm_response = client.post(confirm_url, json={})
                confirm_response.raise_for_status()
                payment_payload = confirm_response.json()
                if not isinstance(payment_payload, dict):
                    return _record_external_payment_failure(
                        runtime,
                        order,
                        module_id=module_id,
                        action_id=payment_action_id,
                        idempotency_key=payment_idempotency_key,
                        reason_code="PAYMENT_EXTERNAL_RESPONSE_INVALID",
                        metadata=payment_metadata,
                        outcome="FAILED_PERMANENT",
                        retryable=False,
                    )
            else:
                return _record_external_payment_failure(
                    runtime,
                    order,
                    module_id=module_id,
                    action_id=payment_action_id,
                    idempotency_key=payment_idempotency_key,
                    reason_code="PAYMENT_REQUIRES_EXTERNAL_CONFIRMATION",
                    metadata=payment_metadata,
                    outcome="FAILED_PERMANENT",
                    retryable=False,
                )
    except (httpx.HTTPError, ValueError) as exc:
        return _record_external_payment_failure(
            runtime,
            order,
            module_id=module_id,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            reason_code="PAYMENT_EXTERNAL_REQUEST_FAILED",
            metadata={**payment_metadata, "error": str(exc)},
            outcome="UNAVAILABLE",
            retryable=True,
        )

    event_payload = _payment_event_payload(payment_payload)
    event_name = str(event_payload.get("event") or "").strip()
    if event_name not in PAYMENT_RESULT_EVENTS:
        event_name = "PAYMENT_FAILED"
    outcome = _safe_payment_outcome(event_name, event_payload.get("outcome"))
    side_effect_state = _safe_side_effect_state(
        event_payload.get("side_effect_state"),
        default="confirmed" if event_name == "PAYMENT_MODE_CHANGED" else "none",
    )
    result_metadata = {
        **payment_metadata,
        "external_payment_id": payment_payload.get("payment_id"),
        "external_payment_status": payment_payload.get("status"),
    }
    reason_code = event_payload.get("reason_code")
    if not isinstance(reason_code, str) or not reason_code.strip():
        reason_code = "EXTERNAL_PAYMENT_FAILED"

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event=event_name,
            source_module=module_id,
            order=order,
            action_id=payment_action_id,
            idempotency_key=payment_idempotency_key,
            outcome=outcome,
            reason_code=reason_code if event_name == "PAYMENT_FAILED" else None,
            severity="low" if event_name == "PAYMENT_MODE_CHANGED" else "high",
            retryable=outcome in {"FAILED_RETRYABLE", "UNAVAILABLE", "TIMEOUT_UNKNOWN"},
            side_effect_state=side_effect_state,
            trigger_event="PAYMENT_REQUIRED",
            metadata=result_metadata,
        ),
    )

    if event_name == "PAYMENT_MODE_CHANGED":
        runtime.store.update_order_payment_method(order.order_id, "external_test_payment")
        updated_order = runtime.store.update_order_status(
            order.order_id,
            OrderStatusUpdate(status="accepted", status_message="Order accepted. External payment confirmed."),
        )
        return updated_order, True

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="ORDER_NEEDS_HUMAN",
            source_module=ORDER_RECEIVER_MODULE_ID,
            order=order,
            action_id=f"order:{order.order_id}:needs-human:payment",
            idempotency_key=f"human:{order.order_id}:payment",
            outcome="NEEDS_HUMAN",
            severity="high",
            retryable=False,
            side_effect_state="none",
            trigger_event="PAYMENT_FAILED",
            metadata=result_metadata,
        ),
    )
    updated_order = runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(
            status="accepted",
            status_message="Order accepted. External payment needs human attention.",
        ),
    )
    return updated_order, False


MODULE_EXECUTORS = (
    ModuleExecutor(
        module_id=PAYMENT_CASH_MODULE_ID,
        lane="payment",
        execute=execute_payment_cash_module,
    ),
    ModuleExecutor(
        module_id=GODPAY_MOCK_MODULE_ID,
        lane="payment",
        execute=execute_godpay_mock_module,
    ),
)


def _external_payment_executors(runtime: PilotRuntime) -> tuple[ModuleExecutor, ...]:
    executors: list[ModuleExecutor] = []
    for manifest in runtime.config.resolved_modules.manifests:
        if _external_payment_manifest(runtime, manifest.module_id) is None:
            continue
        module_id = manifest.module_id
        executors.append(
            ModuleExecutor(
                module_id=module_id,
                lane="payment",
                execute=lambda runtime, order, module_id=module_id: execute_external_payment_module(
                    runtime,
                    order,
                    module_id=module_id,
                ),
            )
        )
    return tuple(executors)


def enabled_module_executors(runtime: PilotRuntime, *, lane: str) -> tuple[ModuleExecutor, ...]:
    available_executors = MODULE_EXECUTORS + _external_payment_executors(runtime)
    active_payment_module_id = effective_payment_module_id(runtime)
    return tuple(
        executor
        for executor in available_executors
        if executor.lane == lane and module_enabled(runtime, executor.module_id)
        if lane != "payment" or not active_payment_module_id or executor.module_id == active_payment_module_id
    )


def execute_module_lane(runtime: PilotRuntime, order: StoredOrder, *, lane: str) -> tuple[StoredOrder, bool]:
    current_order = order
    executors = enabled_module_executors(runtime, lane=lane)
    if lane == "payment" and effective_payment_module_id(runtime) and not executors:
        return execute_unavailable_payment_module(runtime, current_order)
    for executor in executors:
        current_order, allows_next_step = executor.execute(runtime, current_order)
        if not allows_next_step:
            return current_order, False
    return current_order, True


def execute_print_lane(runtime: PilotRuntime, order: StoredOrder) -> StoredOrder:
    print_action_id = f"order:{order.order_id}:print:primary"
    print_idempotency_key = f"print:{order.order_id}:primary"
    configured_mode = runtime.config.print_module_mode.strip().lower()
    print_module_metadata = {
        **build_hardware_profile_metadata(runtime),
        **module_metadata(runtime, PRINT_MODULE_ID),
    }
    adapter = build_print_adapter(runtime.config.print_module_target)
    driver = build_print_driver(
        runtime.config.print_module_driver,
        runtime.config.print_spool_dir,
        runtime.config.print_device_path,
        runtime.config.print_escpos_cut_mode,
    )
    sensor = build_print_sensor(
        source=runtime.config.print_sensor_source,
        status_path=runtime.config.print_sensor_status_path,
        serial_path=runtime.config.print_sensor_serial_path,
        precheck_state=runtime.config.print_sensor_precheck,
        postcheck_state=runtime.config.print_sensor_postcheck,
    )
    precheck = sensor.precheck()
    postcheck = sensor.postcheck()

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="PRINT_REQUESTED",
            source_module=PRINT_MODULE_ID,
            order=order,
            action_id=print_action_id,
            idempotency_key=print_idempotency_key,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            contract_phase=REQUEST_PHASE,
            metadata={
                **print_module_metadata,
                "adapter_target": adapter.target_id,
                "print_driver": driver.driver_id,
                "configured_mode": configured_mode,
                "sensor_source": sensor.source_id,
                "sensor_precheck": precheck.state,
                "sensor_postcheck": postcheck.state,
                **precheck.metadata,
                **postcheck.metadata,
            },
        )
    )

    print_result = build_print_precheck_event(
        runtime=runtime,
        adapter_target=adapter.target_id,
        sensor_observation=precheck,
        order=order,
        action_id=print_action_id,
        idempotency_key=print_idempotency_key,
        hardware_profile_metadata=print_module_metadata,
    )
    if print_result is None:
        print_result = build_print_result_event(
            runtime=runtime,
            adapter=adapter,
            driver=driver,
            configured_mode=configured_mode,
            postcheck_observation=postcheck,
            order=order,
            action_id=print_action_id,
            idempotency_key=print_idempotency_key,
            hardware_profile_metadata=print_module_metadata,
        )
    record_order_flow_event(runtime, print_result)

    if print_result.event == "PRINT_SUCCESS_CONFIRMED":
        return runtime.store.update_order_status(
            order.order_id,
            OrderStatusUpdate(status="accepted", status_message=adapter.confirmed_status_message),
        )

    status_message = adapter.needs_human_status_message
    notification_result: ModuleResultEvent | None = None

    if module_enabled(runtime, NOTIFY_EMAIL_MODULE_ID) and module_supports_fallback(
        runtime,
        PRINT_MODULE_ID,
        print_result.event,
        NOTIFY_EMAIL_MODULE_ID,
    ):
        notification_result = build_notification_result_event(
            runtime=runtime,
            order=order,
            trigger_event=print_result.event,
            adapter_target=adapter.target_id,
            hardware_profile_metadata={
                **print_module_metadata,
                **module_metadata(runtime, NOTIFY_EMAIL_MODULE_ID),
            },
        )
        record_order_flow_event(runtime, notification_result)
        if notification_result.event == "NOTIFICATION_SENT":
            status_message = adapter.alerted_status_message
        else:
            status_message = adapter.alert_failed_status_message

    record_order_flow_event(
        runtime,
        build_result_event(
            runtime=runtime,
            event="ORDER_NEEDS_HUMAN",
            source_module=ORDER_RECEIVER_MODULE_ID,
            order=order,
            action_id=f"order:{order.order_id}:needs-human",
            idempotency_key=f"human:{order.order_id}:print",
            outcome="NEEDS_HUMAN",
            severity="high" if notification_result and notification_result.event == "NOTIFICATION_SENT" else "critical",
            retryable=False,
            side_effect_state="none",
            trigger_event=print_result.event,
            metadata={
                **print_module_metadata,
                "adapter_target": adapter.target_id,
            },
        )
    )
    return runtime.store.update_order_status(
        order.order_id,
        OrderStatusUpdate(status="accepted", status_message=status_message),
    )


def build_print_precheck_event(
    *,
    runtime: PilotRuntime,
    adapter_target: str,
    sensor_observation,
    order: StoredOrder,
    action_id: str,
    idempotency_key: str,
    hardware_profile_metadata: dict[str, object],
) -> ModuleResultEvent | None:
    if adapter_target != "printer":
        return None

    sensor_state = sensor_observation.state
    metadata = {
        **hardware_profile_metadata,
        "adapter_target": adapter_target,
        "sensor_phase": "precheck",
        "sensor_precheck": sensor_state or "ok",
        **sensor_observation.metadata,
    }
    if sensor_state in {"", "ok", "confirmed"}:
        return None
    if sensor_state == "paper_out":
        return build_result_event(
            runtime=runtime,
            event="PAPER_OUT",
            source_module=PRINT_MODULE_ID,
            order=order,
            action_id=action_id,
            idempotency_key=idempotency_key,
            outcome="FAILED_PERMANENT",
            reason_code="PAPER_OUT",
            severity="high",
            retryable=False,
            side_effect_state="none",
            metadata=metadata,
        )
    if sensor_state == "paper_low":
        return build_result_event(
            runtime=runtime,
            event="PAPER_LOW",
            source_module=PRINT_MODULE_ID,
            order=order,
            action_id=action_id,
            idempotency_key=idempotency_key,
            outcome="NEEDS_HUMAN",
            reason_code="PAPER_LOW",
            severity="medium",
            retryable=False,
            side_effect_state="none",
            metadata=metadata,
        )
    if sensor_state in {"offline", "printer_offline"}:
        return build_result_event(
            runtime=runtime,
            event="PRINTER_OFFLINE",
            source_module=PRINT_MODULE_ID,
            order=order,
            action_id=action_id,
            idempotency_key=idempotency_key,
            outcome="UNAVAILABLE",
            reason_code="SENSOR_PRINTER_OFFLINE",
            severity="high",
            retryable=True,
            side_effect_state="none",
            metadata=metadata,
        )
    return build_result_event(
        runtime=runtime,
        event="PRINT_FAILED_PRECHECK",
        source_module=PRINT_MODULE_ID,
        order=order,
        action_id=action_id,
        idempotency_key=idempotency_key,
        outcome="FAILED_PERMANENT",
        reason_code="PRECHECK_SENSOR_BLOCKED",
        severity="high",
        retryable=False,
        side_effect_state="none",
        metadata=metadata,
    )


def build_print_result_event(
    *,
    runtime: PilotRuntime,
    adapter,
    driver,
    configured_mode: str,
    postcheck_observation,
    order: StoredOrder,
    action_id: str,
    idempotency_key: str,
    hardware_profile_metadata: dict[str, object],
) -> ModuleResultEvent:
    decision = adapter.decide(configured_mode)
    metadata = {
        **hardware_profile_metadata,
        "adapter_target": adapter.target_id,
        "print_driver": driver.driver_id,
        "configured_mode": configured_mode or "confirmed",
        "sensor_postcheck": postcheck_observation.state,
        **postcheck_observation.metadata,
    }
    if decision.metadata:
        metadata.update(decision.metadata)
    if decision.event == "PRINT_SUCCESS_CONFIRMED":
        delivery = driver.deliver(target_id=adapter.target_id, order=order, action_id=action_id)
        if delivery.metadata:
            metadata.update(delivery.metadata)
        if not delivery.success:
            return build_result_event(
                runtime=runtime,
                event="PRINT_FAILED_PRECHECK",
                source_module=PRINT_MODULE_ID,
                order=order,
                action_id=action_id,
                idempotency_key=idempotency_key,
                outcome=delivery.outcome,
                reason_code=delivery.reason_code,
                severity=delivery.severity,
                retryable=delivery.retryable,
                side_effect_state=delivery.side_effect_state,
                metadata=metadata,
            )
        if driver.driver_id == "file_spool":
            metadata["side_effect_delivery"] = "artifact_written"
        elif driver.driver_id == "device_path":
            metadata["side_effect_delivery"] = "device_written"
        elif driver.driver_id == "escpos_raw":
            metadata["side_effect_delivery"] = "device_written"
        else:
            metadata["side_effect_delivery"] = "simulated"
        postcheck_event = build_print_postcheck_event(
            runtime=runtime,
            adapter_target=adapter.target_id,
            sensor_observation=postcheck_observation,
            order=order,
            action_id=action_id,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
        if postcheck_event is not None:
            return postcheck_event
    return build_result_event(
        runtime=runtime,
        event=decision.event,
        source_module=PRINT_MODULE_ID,
        order=order,
        action_id=action_id,
        idempotency_key=idempotency_key,
        outcome=decision.outcome,
        reason_code=decision.reason_code,
        severity=decision.severity,
        retryable=decision.retryable,
        side_effect_state=decision.side_effect_state,
        metadata=metadata,
    )


def build_print_postcheck_event(
    *,
    runtime: PilotRuntime,
    adapter_target: str,
    sensor_observation,
    order: StoredOrder,
    action_id: str,
    idempotency_key: str,
    metadata: dict[str, object],
) -> ModuleResultEvent | None:
    if adapter_target != "printer":
        return None

    sensor_state = sensor_observation.state
    if sensor_state in {"", "confirmed", "ok"}:
        return None

    enriched_metadata = dict(metadata)
    enriched_metadata["sensor_phase"] = "postcheck"
    enriched_metadata["sensor_postcheck"] = sensor_state
    enriched_metadata.update(sensor_observation.metadata)

    if sensor_state in {"paper_out", "uncertain", "exit_missing"}:
        reason_code = {
            "paper_out": "POSTCHECK_PAPER_OUT",
            "uncertain": "POSTCHECK_UNCERTAIN",
            "exit_missing": "TICKET_EXIT_NOT_SEEN",
        }[sensor_state]
        return build_result_event(
            runtime=runtime,
            event="PRINT_UNCERTAIN",
            source_module=PRINT_MODULE_ID,
            order=order,
            action_id=action_id,
            idempotency_key=idempotency_key,
            outcome="TIMEOUT_UNKNOWN",
            reason_code=reason_code,
            severity="high",
            retryable=False,
            side_effect_state="unknown",
            metadata=enriched_metadata,
        )

    return build_result_event(
        runtime=runtime,
        event="PRINT_UNCERTAIN",
        source_module=PRINT_MODULE_ID,
        order=order,
        action_id=action_id,
        idempotency_key=idempotency_key,
        outcome="TIMEOUT_UNKNOWN",
        reason_code="POSTCHECK_SENSOR_UNSUPPORTED",
        severity="high",
        retryable=False,
        side_effect_state="unknown",
        metadata=enriched_metadata,
    )


def build_notification_result_event(
    *,
    runtime: PilotRuntime,
    order: StoredOrder,
    trigger_event: str,
    adapter_target: str,
    hardware_profile_metadata: dict[str, object],
) -> ModuleResultEvent:
    configured_mode = runtime.config.notify_email_mode.strip().lower()
    if configured_mode == "failed":
        return build_result_event(
            runtime=runtime,
            event="NOTIFICATION_FAILED",
            source_module=NOTIFY_EMAIL_MODULE_ID,
            order=order,
            action_id=f"order:{order.order_id}:notify:email",
            idempotency_key=f"notify:{order.order_id}:email",
            outcome="FAILED_RETRYABLE",
            reason_code="EMAIL_DELIVERY_FAILED",
            severity="high",
            retryable=True,
            side_effect_state="none",
            trigger_event=trigger_event,
            metadata={
                **hardware_profile_metadata,
                "configured_mode": configured_mode,
                "adapter_target": adapter_target,
            },
        )
    return build_result_event(
        runtime=runtime,
        event="NOTIFICATION_SENT",
        source_module=NOTIFY_EMAIL_MODULE_ID,
        order=order,
        action_id=f"order:{order.order_id}:notify:email",
        idempotency_key=f"notify:{order.order_id}:email",
        outcome="SUCCESS",
        severity="medium",
        retryable=False,
        side_effect_state="confirmed",
        trigger_event=trigger_event,
        metadata={
            **hardware_profile_metadata,
            "configured_mode": configured_mode or "sent",
            "adapter_target": adapter_target,
        },
    )


__all__ = [
    "ModuleExecutor",
    "CHAOSPAY_MOCK_MODULE_ID",
    "GODPAY_MOCK_MODULE_ID",
    "NOTIFY_EMAIL_MODULE_ID",
    "ORDER_RECEIVER_MODULE_ID",
    "PRINT_MODULE_ID",
    "enabled_module_executors",
    "execute_external_payment_module",
    "execute_module_lane",
    "process_accepted_order",
]
