from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LEGACY_DEVICE_NAME_PREFIX = "Lagrange-"
RIZIFY_DEVICE_NAME_PREFIX = "流转者-"
DEVICE_DIGEST_PREFIX_LENGTH = 8
FULL_SHA256_HEX_LENGTH = 64


def generate_rizify_device_name(guid: bytes) -> str:
    if not guid:
        raise ValueError("Device GUID must not be empty")
    digest_id = hashlib.sha256(guid).hexdigest()[:DEVICE_DIGEST_PREFIX_LENGTH]
    return f"{RIZIFY_DEVICE_NAME_PREFIX}{digest_id}"


def should_migrate_device_name(device_name: str) -> bool:
    if device_name.startswith(LEGACY_DEVICE_NAME_PREFIX):
        return True
    if not device_name.startswith(RIZIFY_DEVICE_NAME_PREFIX):
        return False
    suffix = device_name[len(RIZIFY_DEVICE_NAME_PREFIX) :]
    return len(suffix) == FULL_SHA256_HEX_LENGTH and all(
        char in "0123456789abcdefABCDEF" for char in suffix
    )


def _as_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return bytes.fromhex(value) if len(value) % 2 == 0 and _is_hex(value) else value.encode()
    if isinstance(value, Iterable):
        return bytes(int(item) & 0xFF for item in value)
    raise TypeError(f"无法把 {type(value).__name__} 转换为字节数组")


def _is_hex(value: str) -> bool:
    return bool(value) and all(char in "0123456789abcdefABCDEF" for char in value)


def _bytes_json(value: bytes) -> list[int]:
    return list(value)


@dataclass(slots=True)
class SessionStore:
    uin: int = 0
    uid: str = ""
    a2: bytes = b""
    d2: bytes = b""
    d2_key: bytes = b"\x00" * 16
    tgtgt: bytes = b""
    encrypted_a1: bytes = b""
    no_pic_sig: bytes = b""
    qr_sig: bytes = b""
    guid: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    device_name: str = ""
    credentials_updated_at_epoch_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.device_name or should_migrate_device_name(self.device_name):
            self.device_name = generate_rizify_device_name(self.guid)

    @classmethod
    def empty(cls) -> SessionStore:
        guid = secrets.token_bytes(16)
        return cls(guid=guid, d2_key=b"\x00" * 16)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> SessionStore:
        guid = _as_bytes(value.get("guid"))
        device_name = str(value.get("deviceName", value.get("device_name", "")))
        session = cls(
            uin=int(value.get("uin", 0)),
            uid=str(value.get("uid", "")),
            a2=_as_bytes(value.get("a2")),
            d2=_as_bytes(value.get("d2")),
            d2_key=_as_bytes(value.get("d2Key", value.get("d2_key"))) or b"\x00" * 16,
            tgtgt=_as_bytes(value.get("tgtgt")),
            encrypted_a1=_as_bytes(value.get("encryptedA1", value.get("encrypted_a1"))),
            no_pic_sig=_as_bytes(value.get("noPicSig", value.get("no_pic_sig"))),
            qr_sig=_as_bytes(value.get("qrSig", value.get("qr_sig"))),
            guid=guid or secrets.token_bytes(16),
            device_name=device_name,
            credentials_updated_at_epoch_seconds=_optional_int(
                value.get(
                    "credentialsUpdatedAtEpochSeconds",
                    value.get("credentials_updated_at_epoch_seconds"),
                )
            ),
        )
        return session

    @classmethod
    def from_json(cls, text: str) -> SessionStore:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("session.json 根节点必须是对象")
        return cls.from_mapping(value)

    @classmethod
    def from_file(cls, path: Path) -> SessionStore:
        return cls.from_json(path.read_text(encoding="utf-8"))

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "uin": self.uin,
            "uid": self.uid,
            "a2": _bytes_json(self.a2),
            "d2": _bytes_json(self.d2),
            "d2Key": _bytes_json(self.d2_key),
            "tgtgt": _bytes_json(self.tgtgt),
            "encryptedA1": _bytes_json(self.encrypted_a1),
            "noPicSig": _bytes_json(self.no_pic_sig),
            "qrSig": _bytes_json(self.qr_sig),
            "guid": _bytes_json(self.guid),
            "deviceName": self.device_name,
        }
        if self.credentials_updated_at_epoch_seconds is not None:
            value["credentialsUpdatedAtEpochSeconds"] = self.credentials_updated_at_epoch_seconds
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), ensure_ascii=False, indent=2) + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def clear(self) -> None:
        self.credentials_updated_at_epoch_seconds = None
        self.a2 = b""
        self.d2 = b""
        self.d2_key = b"\x00" * 16
        self.tgtgt = b""
        self.encrypted_a1 = b""
        self.no_pic_sig = b""
        self.qr_sig = b""

    def refresh_device_guid(self) -> None:
        self.guid = secrets.token_bytes(16)

    def update_credentials(
        self,
        encrypted_a1: bytes,
        a2: bytes,
        d2: bytes,
        d2_key: bytes,
    ) -> None:
        if not encrypted_a1 or not a2 or not d2 or len(d2_key) != 16:
            raise ValueError("Incomplete login credentials")
        self.encrypted_a1 = encrypted_a1
        self.a2 = a2
        self.d2 = d2
        self.d2_key = d2_key
        self.credentials_updated_at_epoch_seconds = int(time.time())


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
