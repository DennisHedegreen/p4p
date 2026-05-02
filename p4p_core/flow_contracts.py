from __future__ import annotations

from dataclasses import dataclass, field, replace

from .models import ModuleResultEvent
from .modules import ModuleManifest, load_reference_module_catalog


ORDER_RECEIVER_MODULE_ID = "p4p.order.receiver"
PRINT_MODULE_ID = "p4p.order.print"
NOTIFY_EMAIL_MODULE_ID = "p4p.notify.email"
STOCK_BASIC_MODULE_ID = "p4p.stock.basic"
CONTRACT_PHASE_METADATA_KEY = "contract_phase"
TRIGGER_EVENT_METADATA_KEY = "trigger_event"

PRINT_RESULT_EVENTS = frozenset(
    {
        "PRINT_SUCCESS_CONFIRMED",
        "PRINT_FAILED_PRECHECK",
        "PRINT_UNCERTAIN",
        "PRINTER_OFFLINE",
        "PAPER_LOW",
        "PAPER_OUT",
        "PAPER_JAM",
        "PRINT_TIMEOUT",
    }
)
PRINT_FAILURE_EVENTS = PRINT_RESULT_EVENTS - {"PRINT_SUCCESS_CONFIRMED"}
NOTIFICATION_RESULT_EVENTS = frozenset({"NOTIFICATION_SENT", "NOTIFICATION_FAILED"})
PAYMENT_RESULT_EVENTS = frozenset({"PAYMENT_MODE_CHANGED", "PAYMENT_FAILED"})


@dataclass(frozen=True)
class FlowContract:
    transitions: dict[str | None, frozenset[str]]
    expected_sources: dict[str, str]
    expected_phases: dict[str, str]
    notification_trigger_events: frozenset[str]
    human_trigger_events: frozenset[str]


@dataclass(frozen=True)
class FlowExtension:
    required_module_ids: frozenset[str]
    add_transitions: dict[str | None, frozenset[str]]
    priority: int = 100
    replace_transitions: dict[str | None, frozenset[str]] = field(default_factory=dict)
    expected_sources: dict[str, str] = field(default_factory=dict)
    expected_phases: dict[str, str] = field(default_factory=dict)
    notification_trigger_events: frozenset[str] = frozenset()
    human_trigger_events: frozenset[str] = frozenset()

    def applies_to(self, enabled_module_ids: frozenset[str]) -> bool:
        return self.required_module_ids.issubset(enabled_module_ids)


BASE_PILOT_ORDER_FLOW_CONTRACT = FlowContract(
    transitions={
        None: frozenset({"ORDER_ACCEPTED"}),
        "ORDER_ACCEPTED": frozenset({"PRINT_REQUESTED"}),
        "PRINT_REQUESTED": PRINT_RESULT_EVENTS,
        "PRINT_FAILED_PRECHECK": NOTIFICATION_RESULT_EVENTS | {"ORDER_NEEDS_HUMAN"},
        "PRINT_UNCERTAIN": NOTIFICATION_RESULT_EVENTS | {"ORDER_NEEDS_HUMAN"},
        "PRINTER_OFFLINE": NOTIFICATION_RESULT_EVENTS | {"ORDER_NEEDS_HUMAN"},
        "PAPER_LOW": frozenset({"ORDER_NEEDS_HUMAN"}),
        "PAPER_OUT": NOTIFICATION_RESULT_EVENTS | {"ORDER_NEEDS_HUMAN"},
        "PAPER_JAM": frozenset({"ORDER_NEEDS_HUMAN"}),
        "PRINT_TIMEOUT": NOTIFICATION_RESULT_EVENTS | {"ORDER_NEEDS_HUMAN"},
        "NOTIFICATION_SENT": frozenset({"ORDER_NEEDS_HUMAN"}),
        "NOTIFICATION_FAILED": frozenset({"ORDER_NEEDS_HUMAN"}),
        "PRINT_SUCCESS_CONFIRMED": frozenset(),
        "ORDER_NEEDS_HUMAN": frozenset(),
    },
    expected_sources={
        "ORDER_ACCEPTED": ORDER_RECEIVER_MODULE_ID,
        "PRINT_REQUESTED": PRINT_MODULE_ID,
        "PRINT_SUCCESS_CONFIRMED": PRINT_MODULE_ID,
        "PRINT_FAILED_PRECHECK": PRINT_MODULE_ID,
        "PRINT_UNCERTAIN": PRINT_MODULE_ID,
        "PRINTER_OFFLINE": PRINT_MODULE_ID,
        "PAPER_LOW": PRINT_MODULE_ID,
        "PAPER_OUT": PRINT_MODULE_ID,
        "PAPER_JAM": PRINT_MODULE_ID,
        "PRINT_TIMEOUT": PRINT_MODULE_ID,
        "NOTIFICATION_SENT": NOTIFY_EMAIL_MODULE_ID,
        "NOTIFICATION_FAILED": NOTIFY_EMAIL_MODULE_ID,
        "ORDER_NEEDS_HUMAN": ORDER_RECEIVER_MODULE_ID,
    },
    expected_phases={
        "ORDER_ACCEPTED": "result",
        "PRINT_REQUESTED": "request",
        "PRINT_SUCCESS_CONFIRMED": "result",
        "PRINT_FAILED_PRECHECK": "result",
        "PRINT_UNCERTAIN": "result",
        "PRINTER_OFFLINE": "result",
        "PAPER_LOW": "result",
        "PAPER_OUT": "result",
        "PAPER_JAM": "result",
        "PRINT_TIMEOUT": "result",
        "NOTIFICATION_SENT": "result",
        "NOTIFICATION_FAILED": "result",
        "ORDER_NEEDS_HUMAN": "result",
    },
    notification_trigger_events=PRINT_FAILURE_EVENTS,
    human_trigger_events=PRINT_FAILURE_EVENTS,
)


def _merged_transitions(
    base: dict[str | None, frozenset[str]],
    additions: dict[str | None, frozenset[str]],
) -> dict[str | None, frozenset[str]]:
    merged = dict(base)
    for event_name, allowed_next in additions.items():
        merged[event_name] = merged.get(event_name, frozenset()) | allowed_next
    return merged


def _extend_contract(
    contract: FlowContract,
    *,
    replace_transitions: dict[str | None, frozenset[str]] | None = None,
    add_transitions: dict[str | None, frozenset[str]] | None = None,
    expected_sources: dict[str, str] | None = None,
    expected_phases: dict[str, str] | None = None,
    notification_trigger_events: frozenset[str] | None = None,
    human_trigger_events: frozenset[str] | None = None,
) -> FlowContract:
    transitions = dict(contract.transitions)
    if replace_transitions:
        transitions.update(replace_transitions)
    if add_transitions:
        transitions = _merged_transitions(transitions, add_transitions)
    return replace(
        contract,
        transitions=transitions,
        expected_sources=contract.expected_sources | (expected_sources or {}),
        expected_phases=contract.expected_phases | (expected_phases or {}),
        notification_trigger_events=(
            contract.notification_trigger_events
            if notification_trigger_events is None
            else contract.notification_trigger_events | notification_trigger_events
        ),
        human_trigger_events=(
            contract.human_trigger_events
            if human_trigger_events is None
            else contract.human_trigger_events | human_trigger_events
        ),
    )


PILOT_ORDER_FLOW_EXTENSIONS = (
    FlowExtension(
        required_module_ids=frozenset({STOCK_BASIC_MODULE_ID}),
        priority=100,
        add_transitions={
            "ORDER_ACCEPTED": frozenset({"ORDER_VALIDATED", "ITEM_NOT_POSSIBLE"}),
            "ORDER_VALIDATED": frozenset({"PRINT_REQUESTED"}),
            "ITEM_NOT_POSSIBLE": frozenset({"ORDER_NEEDS_HUMAN"}),
        },
        expected_sources={
            "ORDER_VALIDATED": STOCK_BASIC_MODULE_ID,
            "ITEM_NOT_POSSIBLE": STOCK_BASIC_MODULE_ID,
        },
        expected_phases={
            "ORDER_VALIDATED": "result",
            "ITEM_NOT_POSSIBLE": "result",
        },
        human_trigger_events=frozenset({"ITEM_NOT_POSSIBLE"}),
    ),
)


def _is_payment_flow_module(manifest: ModuleManifest) -> bool:
    module_class = str(manifest.raw.get("module_class") or manifest.raw.get("type") or "").strip()
    return (
        module_class == "payment"
        and "PAYMENT_REQUIRED" in manifest.input_events
        and PAYMENT_RESULT_EVENTS.issubset(set(manifest.output_events))
    )


def _enabled_payment_flow_module_id(
    enabled_module_ids: tuple[str, ...],
    *,
    module_manifests: tuple[ModuleManifest, ...] | list[ModuleManifest] | None = None,
) -> str | None:
    catalog = load_reference_module_catalog() | {
        manifest.module_id: manifest for manifest in (module_manifests or ())
    }
    for module_id in enabled_module_ids:
        manifest = catalog.get(module_id)
        if manifest is not None and _is_payment_flow_module(manifest):
            return module_id
    return None


def _payment_flow_extensions(
    enabled_module_ids: tuple[str, ...],
    *,
    module_manifests: tuple[ModuleManifest, ...] | list[ModuleManifest] | None = None,
) -> tuple[FlowExtension, ...]:
    payment_module_id = _enabled_payment_flow_module_id(
        enabled_module_ids,
        module_manifests=module_manifests,
    )
    if payment_module_id is None:
        return ()
    return (
        FlowExtension(
            required_module_ids=frozenset({payment_module_id}),
            priority=100,
            add_transitions={
                "ORDER_ACCEPTED": frozenset({"PAYMENT_REQUIRED"}),
                "PAYMENT_REQUIRED": PAYMENT_RESULT_EVENTS,
                "PAYMENT_MODE_CHANGED": frozenset({"PRINT_REQUESTED"}),
                "PAYMENT_FAILED": frozenset({"ORDER_NEEDS_HUMAN"}),
            },
            expected_sources={
                "PAYMENT_REQUIRED": payment_module_id,
                "PAYMENT_MODE_CHANGED": payment_module_id,
                "PAYMENT_FAILED": payment_module_id,
            },
            expected_phases={
                "PAYMENT_REQUIRED": "request",
                "PAYMENT_MODE_CHANGED": "result",
                "PAYMENT_FAILED": "result",
            },
            human_trigger_events=frozenset({"PAYMENT_FAILED"}),
        ),
        FlowExtension(
            required_module_ids=frozenset({STOCK_BASIC_MODULE_ID, payment_module_id}),
            priority=200,
            add_transitions={
                "ORDER_VALIDATED": frozenset({"PAYMENT_REQUIRED"}),
            },
        ),
    )


def _flow_extension_sort_key(extension: FlowExtension) -> tuple[int, tuple[str, ...]]:
    return (
        extension.priority,
        len(extension.required_module_ids),
        tuple(sorted(extension.required_module_ids)),
    )


def build_pilot_order_flow_contract(
    enabled_module_ids: tuple[str, ...] | list[str] | None = None,
    *,
    module_manifests: tuple[ModuleManifest, ...] | list[ModuleManifest] | None = None,
) -> FlowContract:
    enabled_sequence = tuple(enabled_module_ids or ())
    enabled = frozenset(enabled_sequence)
    contract = BASE_PILOT_ORDER_FLOW_CONTRACT
    flow_extensions = PILOT_ORDER_FLOW_EXTENSIONS + _payment_flow_extensions(
        enabled_sequence,
        module_manifests=module_manifests,
    )

    for extension in sorted(flow_extensions, key=_flow_extension_sort_key):
        if not extension.applies_to(enabled):
            continue
        contract = _extend_contract(
            contract,
            replace_transitions=extension.replace_transitions,
            add_transitions=extension.add_transitions,
            expected_sources=extension.expected_sources,
            expected_phases=extension.expected_phases,
            notification_trigger_events=extension.notification_trigger_events,
            human_trigger_events=extension.human_trigger_events,
        )

    return contract


def _contract_phase(event: ModuleResultEvent) -> str | None:
    return _metadata_token(event, CONTRACT_PHASE_METADATA_KEY)


def _trigger_event(event: ModuleResultEvent) -> str | None:
    return _metadata_token(event, TRIGGER_EVENT_METADATA_KEY)


def _metadata_token(event: ModuleResultEvent, key: str) -> str | None:
    if event.metadata is None:
        return None
    value = event.metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _latest_matching_event(
    existing_events: list[ModuleResultEvent],
    allowed_events: frozenset[str],
) -> ModuleResultEvent | None:
    for event in reversed(existing_events):
        if event.event in allowed_events:
            return event
    return None


def validate_pilot_order_event_flow(
    existing_events: list[ModuleResultEvent],
    next_event: ModuleResultEvent,
    *,
    enabled_module_ids: tuple[str, ...] | list[str] | None = None,
    module_manifests: tuple[ModuleManifest, ...] | list[ModuleManifest] | None = None,
) -> None:
    if next_event.order_id is None:
        raise ValueError(f"Pilot order flow events must carry order_id: {next_event.event}")

    contract = build_pilot_order_flow_contract(
        enabled_module_ids,
        module_manifests=module_manifests,
    )
    previous_event = existing_events[-1] if existing_events else None
    previous_name = previous_event.event if previous_event is not None else None
    allowed_next = contract.transitions.get(previous_name)

    if allowed_next is None:
        raise ValueError(f"Pilot order flow contract has no transition rule for {previous_name}")
    if next_event.event not in allowed_next:
        raise ValueError(
            f"Pilot order flow contract forbids {next_event.event} after {previous_name or 'FLOW_START'}"
        )

    expected_source = contract.expected_sources.get(next_event.event)
    if expected_source is not None and next_event.source_module != expected_source:
        raise ValueError(
            f"Pilot order flow contract expects source {expected_source} for {next_event.event}, "
            f"got {next_event.source_module}"
        )

    expected_phase = contract.expected_phases.get(next_event.event)
    actual_phase = _contract_phase(next_event)
    if expected_phase is not None and actual_phase != expected_phase:
        raise ValueError(
            f"Pilot order flow contract expects contract_phase={expected_phase} for {next_event.event}, "
            f"got {actual_phase!r}"
        )

    if next_event.event in NOTIFICATION_RESULT_EVENTS:
        if previous_event is None or previous_event.event not in contract.notification_trigger_events:
            raise ValueError(
                f"Pilot order flow contract requires a notification trigger before {next_event.event}"
            )
        trigger_event = _trigger_event(next_event)
        if trigger_event != previous_event.event:
            raise ValueError(
                f"Pilot order flow contract requires notification trigger_event={previous_event.event}, "
                f"got {trigger_event!r}"
            )

    if next_event.event == "ORDER_NEEDS_HUMAN":
        triggering_event = _latest_matching_event(existing_events, contract.human_trigger_events)
        if triggering_event is None:
            raise ValueError("Pilot order flow contract requires a trigger event before ORDER_NEEDS_HUMAN")
        trigger_event = _trigger_event(next_event)
        if trigger_event != triggering_event.event:
            raise ValueError(
                f"Pilot order flow contract requires ORDER_NEEDS_HUMAN trigger_event={triggering_event.event}, "
                f"got {trigger_event!r}"
            )


__all__ = [
    "BASE_PILOT_ORDER_FLOW_CONTRACT",
    "CONTRACT_PHASE_METADATA_KEY",
    "FlowContract",
    "FlowExtension",
    "NOTIFY_EMAIL_MODULE_ID",
    "NOTIFICATION_RESULT_EVENTS",
    "ORDER_RECEIVER_MODULE_ID",
    "PAYMENT_RESULT_EVENTS",
    "PRINT_FAILURE_EVENTS",
    "PRINT_MODULE_ID",
    "PRINT_RESULT_EVENTS",
    "PILOT_ORDER_FLOW_EXTENSIONS",
    "STOCK_BASIC_MODULE_ID",
    "TRIGGER_EVENT_METADATA_KEY",
    "build_pilot_order_flow_contract",
    "validate_pilot_order_event_flow",
]
