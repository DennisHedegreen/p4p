from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    profile_id: str
    label: str
    base_profile: str
    enabled_addons: tuple[str, ...]
    print_module_target: str
    print_module_driver: str
    print_sensor_source: str
    print_escpos_cut_mode: str = "partial"
    backup_print_target: str = ""
    backup_print_driver: str = "file_spool"
    alert_target: str = ""
    alert_mode: str = "completed"
    pickup_board_target: str = ""


_HARDWARE_PROFILES = {
    "reference_printer": HardwareProfile(
        profile_id="reference_printer",
        label="Reference printer",
        base_profile="printer_box",
        enabled_addons=(),
        print_module_target="printer",
        print_module_driver="simulated",
        print_sensor_source="simulated",
        print_escpos_cut_mode="partial",
    ),
    "operator_screen": HardwareProfile(
        profile_id="operator_screen",
        label="Screen only",
        base_profile="screen_only",
        enabled_addons=(),
        print_module_target="screen",
        print_module_driver="simulated",
        print_sensor_source="simulated",
        print_escpos_cut_mode="partial",
    ),
    "spool_printer": HardwareProfile(
        profile_id="spool_printer",
        label="Spool printer",
        base_profile="printer_box",
        enabled_addons=("backup_spool",),
        print_module_target="printer",
        print_module_driver="file_spool",
        print_sensor_source="simulated",
        print_escpos_cut_mode="partial",
    ),
    "box_v1": HardwareProfile(
        profile_id="box_v1",
        label="Printer box",
        base_profile="printer_box",
        enabled_addons=("ticket_printer",),
        print_module_target="printer",
        print_module_driver="escpos_raw",
        print_sensor_source="serial_status",
        print_escpos_cut_mode="partial",
    ),
    "box_v1_counter": HardwareProfile(
        profile_id="box_v1_counter",
        label="Counter box",
        base_profile="counter_box",
        enabled_addons=("ticket_printer", "backup_spool", "order_alert", "pickup_board"),
        print_module_target="printer",
        print_module_driver="escpos_raw",
        print_sensor_source="serial_status",
        print_escpos_cut_mode="partial",
        backup_print_target="backup_spool",
        backup_print_driver="file_spool",
        alert_target="counter_bell",
        alert_mode="completed",
        pickup_board_target="counter_screen",
    ),
}

_BASE_PROFILE_LABELS = {
    "screen_only": "Screen only",
    "printer_box": "Printer box",
    "counter_box": "Counter box",
}

_ADDON_LABELS = {
    "ticket_printer": "Ticket printer",
    "backup_spool": "Backup print spool",
    "order_alert": "Bell or local alert",
    "pickup_board": "Pickup board",
}


def resolve_hardware_profile(profile_id: str) -> HardwareProfile:
    normalized = profile_id.strip().lower()
    if not normalized:
        return _HARDWARE_PROFILES["reference_printer"]
    return _HARDWARE_PROFILES.get(normalized, _HARDWARE_PROFILES["reference_printer"])


def list_hardware_profiles() -> tuple[HardwareProfile, ...]:
    return tuple(_HARDWARE_PROFILES.values())

def list_hardware_base_profiles() -> tuple[dict[str, str], ...]:
    return tuple({"id": profile_id, "label": label} for profile_id, label in _BASE_PROFILE_LABELS.items())


def list_hardware_addons() -> tuple[dict[str, str], ...]:
    return tuple({"id": addon_id, "label": label} for addon_id, label in _ADDON_LABELS.items())


def hardware_profile_state(profile_id: str) -> dict[str, object]:
    profile = resolve_hardware_profile(profile_id)
    return {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "base_profile": profile.base_profile,
        "enabled_addons": list(profile.enabled_addons),
    }


def resolve_base_profile_label(profile_id: str) -> str:
    return _BASE_PROFILE_LABELS.get(profile_id.strip(), profile_id.strip())


def resolve_addon_label(addon_id: str) -> str:
    return _ADDON_LABELS.get(addon_id.strip(), addon_id.strip())


def profile_id_from_state(base_profile: str, enabled_addons: list[str] | tuple[str, ...]) -> str | None:
    normalized_base = base_profile.strip()
    normalized_addons = tuple(sorted({str(addon).strip() for addon in enabled_addons if str(addon).strip()}))
    for profile in _HARDWARE_PROFILES.values():
        if profile.base_profile != normalized_base:
            continue
        if tuple(sorted(profile.enabled_addons)) == normalized_addons:
            return profile.profile_id
    return None


__all__ = [
    "HardwareProfile",
    "hardware_profile_state",
    "list_hardware_addons",
    "list_hardware_base_profiles",
    "list_hardware_profiles",
    "profile_id_from_state",
    "resolve_addon_label",
    "resolve_base_profile_label",
    "resolve_hardware_profile",
]
