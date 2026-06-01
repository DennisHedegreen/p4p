from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from p4p_core import OrderItem, StoredOrder, utc_now

from pilot_node.print_drivers import build_print_driver


ORDER_PRINT_BACKUP_MODULE_ID = "p4p.order.print.backup"
ORDER_ALERT_BASIC_MODULE_ID = "p4p.order.alert.basic"
PICKUP_BOARD_BASIC_MODULE_ID = "p4p.pickup.board.basic"

_PICKUP_BOARD_VISIBLE_STATUSES = {"accepted", "ready"}
_PICKUP_BOARD_STATUS_PRIORITY = {"ready": 0, "accepted": 1}


def pickup_board_entries(orders: list[StoredOrder]) -> list[dict[str, Any]]:
    visible = [order for order in orders if order.status in _PICKUP_BOARD_VISIBLE_STATUSES]
    visible.sort(
        key=lambda order: (
            _PICKUP_BOARD_STATUS_PRIORITY.get(order.status, 9),
            order.estimated_ready or order.requested_at,
            order.requested_at,
        )
    )
    return [
        {
            "order_id": order.order_id,
            "status": order.status,
            "status_message": order.status_message,
            "payment_method": order.payment_method,
            "requested_at": order.requested_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "estimated_ready": order.estimated_ready.isoformat() if order.estimated_ready is not None else None,
        }
        for order in visible
    ]


def run_backup_print_self_test(config) -> dict[str, Any]:
    now = utc_now()
    sample_order = StoredOrder(
        order_id=f"selftest-{secrets.token_hex(4)}",
        customer_name="P4P Self Test",
        customer_contact="+4500000000",
        fulfillment="pickup",
        items=[OrderItem(id="self-test-ticket", quantity=1)],
        note="Backup print self-test",
        client_version="pilot-node-self-test",
        status="accepted",
        payment_method="pay_at_pickup",
        status_message="Self-test ticket",
        requested_at=now,
        updated_at=now,
        estimated_ready=now + timedelta(minutes=15),
    )
    driver = build_print_driver(
        config.backup_print_driver,
        config.backup_print_spool_dir,
        config.backup_print_device_path,
        config.backup_print_escpos_cut_mode,
    )
    delivery = driver.deliver(
        target_id=config.backup_print_target,
        order=sample_order,
        action_id=f"{ORDER_PRINT_BACKUP_MODULE_ID}:self-test:{sample_order.order_id}",
    )
    result_event = "ACTION_COMPLETED" if delivery.success else "RETRY_SCHEDULED"
    metadata = delivery.metadata or {}
    return {
        "module_id": ORDER_PRINT_BACKUP_MODULE_ID,
        "events": ["OUTBOUND_ACTION_REQUESTED", result_event],
        "success": delivery.success,
        "outcome": delivery.outcome,
        "reason_code": delivery.reason_code,
        "retryable": delivery.retryable,
        "severity": delivery.severity,
        "side_effect_state": delivery.side_effect_state,
        "target": config.backup_print_target,
        "driver": driver.driver_id,
        "artifact_path": metadata.get("spool_path") or metadata.get("device_path"),
        "checked_at": now.isoformat(),
        "details": metadata,
    }


def run_order_alert_self_test(config) -> dict[str, Any]:
    now = utc_now()
    normalized_mode = config.alert_mode.strip().lower() or "completed"
    success = normalized_mode not in {"retry", "offline", "unavailable"}
    result_event = "ACTION_COMPLETED" if success else "RETRY_SCHEDULED"
    return {
        "module_id": ORDER_ALERT_BASIC_MODULE_ID,
        "events": ["OUTBOUND_ACTION_REQUESTED", result_event],
        "success": success,
        "outcome": "SUCCESS" if success else "FAILED_RETRYABLE",
        "reason_code": None if success else "ALERT_TARGET_UNAVAILABLE",
        "retryable": not success,
        "severity": "low" if success else "high",
        "side_effect_state": "confirmed" if success else "none",
        "target": config.alert_target,
        "mode": normalized_mode,
        "checked_at": now.isoformat(),
        "details": {
            "alert_target": config.alert_target,
            "configured_mode": normalized_mode,
        },
    }


__all__ = [
    "ORDER_ALERT_BASIC_MODULE_ID",
    "ORDER_PRINT_BACKUP_MODULE_ID",
    "PICKUP_BOARD_BASIC_MODULE_ID",
    "pickup_board_entries",
    "run_backup_print_self_test",
    "run_order_alert_self_test",
]
