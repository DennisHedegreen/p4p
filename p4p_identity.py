from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


KEY_PREFIX = "ed25519:"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _strip_prefix(value: str, *, field_name: str) -> str:
    if not value.startswith(KEY_PREFIX):
        raise ValueError(f"{field_name} must start with {KEY_PREFIX}")
    return value.removeprefix(KEY_PREFIX)


def generate_private_key() -> str:
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return f"{KEY_PREFIX}{_b64encode(raw)}"


def public_key_from_private(private_key_value: str) -> str:
    raw = _b64decode(_strip_prefix(private_key_value, field_name="private_key"))
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    public_key = private_key.public_key()
    public_raw = public_key.public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return f"{KEY_PREFIX}{_b64encode(public_raw)}"


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def signing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "signature" and value is not None}


def sign_payload(payload: dict[str, Any], private_key_value: str) -> str:
    raw = _b64decode(_strip_prefix(private_key_value, field_name="private_key"))
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    signature = private_key.sign(canonical_bytes(signing_payload(payload)))
    return f"{KEY_PREFIX}{_b64encode(signature)}"


def verify_payload(payload: dict[str, Any], public_key_value: str, signature_value: str) -> bool:
    public_raw = _b64decode(_strip_prefix(public_key_value, field_name="public_key"))
    signature_raw = _b64decode(_strip_prefix(signature_value, field_name="signature"))
    public_key = Ed25519PublicKey.from_public_bytes(public_raw)
    try:
        public_key.verify(signature_raw, canonical_bytes(signing_payload(payload)))
    except InvalidSignature:
        return False
    return True


def load_or_create_private_key(path: Path | None) -> str:
    if path is None:
        return generate_private_key()

    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        private_key = data.get("private_key")
        if not isinstance(private_key, str):
            raise ValueError(f"{path} is missing private_key")
        return private_key

    private_key = generate_private_key()
    public_key = public_key_from_private(private_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "key_type": "ed25519",
                "private_key": private_key,
                "public_key": public_key,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return private_key
