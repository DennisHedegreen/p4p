#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4p_identity import load_or_create_private_key, public_key_from_private


KEY_FILES = (
    "registry-a-key.json",
    "registry-b-key.json",
    "demo-node-identity.json",
    "demo-node-root.json",
    "pilot-node-key.json",
)
SECRET_FILES = {
    "registry-a.secret.env": "P4P_REGISTRY_ADMIN_TOKEN",
    "registry-b.secret.env": "P4P_REGISTRY_ADMIN_TOKEN",
    "pilot-node.secret.env": "P4P_OPERATOR_TOKEN",
}
PROOF_DATABASES = ("registry-a.sqlite3", "registry-b.sqlite3")
PILOT_DATABASES = PROOF_DATABASES + ("pilot-node.sqlite3",)


class StateError(RuntimeError):
    pass


def private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise StateError(f"{path} must be a regular directory")
    path.chmod(0o700)
    return path


def require_private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise StateError(f"{path} must be a regular file")
    if path.stat().st_mode & 0o777 != 0o600:
        raise StateError(f"{path} must have mode 0600")


def write_exclusive_private(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise StateError(f"refusing to overwrite {path}") from exc
    path.chmod(0o600)


def read_secret(path: Path, variable: str) -> str:
    require_private_file(path)
    prefix = f"{variable}="
    values = [line.removeprefix(prefix).strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(prefix)]
    if len(values) != 1 or len(values[0]) < 43:
        raise StateError(f"{path} must contain one strong {variable}")
    return values[0]


def resolve_owner(owner: str | None) -> tuple[int, int] | None:
    if not owner:
        return None
    try:
        record = pwd.getpwnam(owner)
    except KeyError as exc:
        raise StateError(f"unknown state owner: {owner}") from exc
    return record.pw_uid, record.pw_gid


def apply_state_owner(state_dir: Path, owner: str | None) -> None:
    resolved = resolve_owner(owner)
    if resolved is None:
        return
    uid, gid = resolved
    os.chown(state_dir, uid, gid)
    for path in state_dir.iterdir():
        os.chown(path, uid, gid)


def init_runtime_state(
    state_dir: Path,
    secrets_dir: Path,
    *,
    state_owner: str | None = None,
) -> dict[str, Any]:
    private_directory(state_dir)
    private_directory(secrets_dir)

    public_keys: dict[str, str] = {}
    for filename in KEY_FILES:
        key_path = state_dir / filename
        private_key = load_or_create_private_key(key_path)
        public_keys[filename] = public_key_from_private(private_key)

    for filename, variable in SECRET_FILES.items():
        secret_path = secrets_dir / filename
        if not secret_path.exists():
            write_exclusive_private(
                secret_path,
                f"{variable}={secrets.token_urlsafe(48)}\n",
            )
        read_secret(secret_path, variable)

    apply_state_owner(state_dir, state_owner)

    return {
        "status": "initialized",
        "state_dir": str(state_dir),
        "secrets_dir": str(secrets_dir),
        "public_keys": public_keys,
        "state_owner": state_owner or pwd.getpwuid(state_dir.stat().st_uid).pw_name,
        "secrets_printed": False,
    }


def database_names(profile: str) -> tuple[str, ...]:
    return PILOT_DATABASES if profile == "pilot" else PROOF_DATABASES


def check_sqlite(path: Path) -> None:
    require_private_file(path)
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        result = connection.execute("PRAGMA integrity_check").fetchone()
        connection.close()
    except sqlite3.Error as exc:
        raise StateError(f"SQLite check failed for {path}: {exc}") from exc
    if not result or result[0] != "ok":
        raise StateError(f"SQLite integrity check failed for {path}")


def audit_runtime_state(
    state_dir: Path,
    secrets_dir: Path,
    *,
    profile: str,
    require_databases: bool,
    state_owner: str | None = None,
) -> dict[str, Any]:
    for directory in (state_dir, secrets_dir):
        if directory.is_symlink() or not directory.is_dir():
            raise StateError(f"missing private directory: {directory}")
        if directory.stat().st_mode & 0o077:
            raise StateError(f"{directory} must not be accessible by group or other users")

    public_keys: dict[str, str] = {}
    expected_owner = resolve_owner(state_owner)
    if expected_owner is not None and state_dir.stat().st_uid != expected_owner[0]:
        raise StateError(f"{state_dir} is not owned by {state_owner}")
    for filename in KEY_FILES:
        path = state_dir / filename
        require_private_file(path)
        if expected_owner is not None and path.stat().st_uid != expected_owner[0]:
            raise StateError(f"{path} is not owned by {state_owner}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        private_key = payload.get("private_key")
        if not isinstance(private_key, str):
            raise StateError(f"{path} is missing private_key")
        derived = public_key_from_private(private_key)
        if payload.get("public_key") != derived:
            raise StateError(f"{path} public key does not match its private key")
        public_keys[filename] = derived
    if len(set(public_keys.values())) != len(public_keys):
        raise StateError("runtime identities must not share signing keys")

    for filename, variable in SECRET_FILES.items():
        read_secret(secrets_dir / filename, variable)

    checked_databases: list[str] = []
    for filename in database_names(profile):
        path = state_dir / filename
        if not path.exists():
            if require_databases:
                raise StateError(f"missing required database: {path}")
            continue
        check_sqlite(path)
        if expected_owner is not None and path.stat().st_uid != expected_owner[0]:
            raise StateError(f"{path} is not owned by {state_owner}")
        checked_databases.append(filename)

    return {
        "status": "passed",
        "profile": profile,
        "key_count": len(public_keys),
        "keys_are_distinct": True,
        "state_owner": state_owner or pwd.getpwuid(state_dir.stat().st_uid).pw_name,
        "secret_count": len(SECRET_FILES),
        "databases": checked_databases,
        "secrets_printed": False,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_sqlite(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    target.chmod(0o600)


def backup_runtime_state(state_dir: Path, secrets_dir: Path, output_dir: Path) -> dict[str, Any]:
    audit_runtime_state(
        state_dir,
        secrets_dir,
        profile="proof",
        require_databases=False,
    )
    if output_dir.exists():
        raise StateError(f"refusing to overwrite backup directory: {output_dir}")
    private_directory(output_dir)
    backup_state = private_directory(output_dir / "state")
    backup_secrets = private_directory(output_dir / "secrets")

    entries: list[dict[str, str]] = []
    for source_dir, target_dir, names in (
        (state_dir, backup_state, KEY_FILES),
        (secrets_dir, backup_secrets, tuple(SECRET_FILES)),
    ):
        for filename in names:
            source = source_dir / filename
            require_private_file(source)
            target = target_dir / filename
            shutil.copyfile(source, target)
            target.chmod(0o600)
            entries.append({"path": str(target.relative_to(output_dir)), "sha256": sha256_file(target)})

    for filename in PILOT_DATABASES:
        source = state_dir / filename
        if not source.exists():
            continue
        check_sqlite(source)
        target = backup_state / filename
        copy_sqlite(source, target)
        entries.append({"path": str(target.relative_to(output_dir)), "sha256": sha256_file(target)})

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(entries, key=lambda entry: entry["path"]),
    }
    manifest_path = output_dir / "manifest.json"
    write_exclusive_private(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"status": "created", "backup_dir": str(output_dir), "file_count": len(entries)}


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / "manifest.json"
    require_private_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise StateError("unsupported or invalid backup manifest")
    checked = 0
    for entry in manifest["files"]:
        relative = Path(str(entry.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise StateError(f"unsafe backup path: {relative}")
        path = backup_dir / relative
        require_private_file(path)
        if sha256_file(path) != entry.get("sha256"):
            raise StateError(f"backup hash mismatch: {relative}")
        if path.suffix == ".sqlite3":
            check_sqlite(path)
        checked += 1
    return {"status": "passed", "backup_dir": str(backup_dir), "file_count": checked}


def restore_copy(
    backup_dir: Path,
    target_root: Path,
    *,
    state_owner: str | None = None,
) -> dict[str, Any]:
    verify_backup(backup_dir)
    if target_root.exists():
        raise StateError(f"refusing to overwrite restore target: {target_root}")
    private_directory(target_root)
    for name in ("state", "secrets"):
        source = backup_dir / name
        target = target_root / name
        shutil.copytree(source, target)
        target.chmod(0o700)
        for path in target.iterdir():
            path.chmod(0o600)
    apply_state_owner(target_root / "state", state_owner)
    return {
        "status": "restored_copy",
        "state_dir": str(target_root / "state"),
        "secrets_dir": str(target_root / "secrets"),
        "state_owner": state_owner or pwd.getpwuid((target_root / "state").stat().st_uid).pw_name,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision and verify private P4P runtime state.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("init", "audit"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--state-dir", type=Path, required=True)
        subparser.add_argument("--secrets-dir", type=Path, required=True)
        subparser.add_argument("--state-owner")
        if command == "audit":
            subparser.add_argument("--profile", choices=("proof", "pilot"), default="proof")
            subparser.add_argument("--require-databases", action="store_true")

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--state-dir", type=Path, required=True)
    backup_parser.add_argument("--secrets-dir", type=Path, required=True)
    backup_parser.add_argument("--output-dir", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify-backup")
    verify_parser.add_argument("--backup-dir", type=Path, required=True)

    restore_parser = subparsers.add_parser("restore-copy")
    restore_parser.add_argument("--backup-dir", type=Path, required=True)
    restore_parser.add_argument("--target-root", type=Path, required=True)
    restore_parser.add_argument("--state-owner")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        result = init_runtime_state(
            args.state_dir,
            args.secrets_dir,
            state_owner=args.state_owner,
        )
    elif args.command == "audit":
        result = audit_runtime_state(
            args.state_dir,
            args.secrets_dir,
            profile=args.profile,
            require_databases=args.require_databases,
            state_owner=args.state_owner,
        )
    elif args.command == "backup":
        result = backup_runtime_state(args.state_dir, args.secrets_dir, args.output_dir)
    elif args.command == "verify-backup":
        result = verify_backup(args.backup_dir)
    else:
        result = restore_copy(
            args.backup_dir,
            args.target_root,
            state_owner=args.state_owner,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, StateError, json.JSONDecodeError) as exc:
        print(f"P4P runtime-state error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
