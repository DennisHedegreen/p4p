from __future__ import annotations

from typing import Literal

PROTOCOL_VERSION = "0.1"
HEARTBEAT_TTL_SECONDS = 180
MAX_SIGNED_AT_FUTURE_SKEW_SECONDS = 30
DEFAULT_RADIUS_KM = 5.0
DEFAULT_LOOPBACK_CORS_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

NODE_ID_PATTERN = r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3,}$"
CATEGORY_PATTERN = r"^[a-z0-9][a-z0-9-]*$"

OrderMode = Literal["disabled", "menu_only", "test", "live"]
OrderStatus = Literal["new", "accepted", "rejected", "ready", "completed", "cancelled"]
DelegationRole = Literal["primary", "backup"]
DelegationCapability = Literal["announce", "heartbeat"]
ManifestKeyStatus = Literal["active", "revoked"]
