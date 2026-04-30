from __future__ import annotations

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
from pilot_node.runtime import PilotRuntime


ORDER_RECEIVER_MODULE_ID = "p4p.order.receiver"
PRINT_MODULE_ID = "p4p.order.print"
NOTIFY_EMAIL_MODULE_ID = "p4p.notify.email"
INTERNAL_RUNTIME_MODULE_IDS = frozenset({ORDER_RECEIVER_MODULE_ID})
REQUEST_PHASE = "request"
RESULT_PHASE = "result"


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
        enabled_module_ids=runtime.config.resolved_modules.module_ids,
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
    if not module_enabled(runtime, PRINT_MODULE_ID):
        return accepted_order
    return execute_print_lane(runtime, accepted_order)


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
    "NOTIFY_EMAIL_MODULE_ID",
    "ORDER_RECEIVER_MODULE_ID",
    "PRINT_MODULE_ID",
    "process_accepted_order",
]
