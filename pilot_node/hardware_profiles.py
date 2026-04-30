from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    profile_id: str
    print_module_target: str
    print_module_driver: str
    print_sensor_source: str
    print_escpos_cut_mode: str = "partial"


_HARDWARE_PROFILES = {
    "reference_printer": HardwareProfile(
        profile_id="reference_printer",
        print_module_target="printer",
        print_module_driver="simulated",
        print_sensor_source="simulated",
        print_escpos_cut_mode="partial",
    ),
    "operator_screen": HardwareProfile(
        profile_id="operator_screen",
        print_module_target="screen",
        print_module_driver="simulated",
        print_sensor_source="simulated",
        print_escpos_cut_mode="partial",
    ),
    "spool_printer": HardwareProfile(
        profile_id="spool_printer",
        print_module_target="printer",
        print_module_driver="file_spool",
        print_sensor_source="simulated",
        print_escpos_cut_mode="partial",
    ),
    "box_v1": HardwareProfile(
        profile_id="box_v1",
        print_module_target="printer",
        print_module_driver="escpos_raw",
        print_sensor_source="serial_status",
        print_escpos_cut_mode="partial",
    ),
}


def resolve_hardware_profile(profile_id: str) -> HardwareProfile:
    normalized = profile_id.strip().lower()
    if not normalized:
        return _HARDWARE_PROFILES["reference_printer"]
    return _HARDWARE_PROFILES.get(normalized, _HARDWARE_PROFILES["reference_printer"])


__all__ = ["HardwareProfile", "resolve_hardware_profile"]
