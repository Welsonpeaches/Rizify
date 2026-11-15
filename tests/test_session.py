from __future__ import annotations

import json
import re
from pathlib import Path

from acidify_core.session import (
    FULL_SHA256_HEX_LENGTH,
    SessionStore,
    generate_rizify_device_name,
)
from rizify.session import load_session

DEVICE_NAME = re.compile(r"^流转者-[0-9a-f]{8}$")


def test_device_name_uses_first_eight_lowercase_sha256_chars() -> None:
    guid = bytes.fromhex("00112233445566778899aabbccddeeff")
    assert generate_rizify_device_name(guid) == "流转者-a8faed6a"


def test_legacy_lagrange_name_is_migrated() -> None:
    session = SessionStore.from_mapping(
        {"guid": list(bytes(16)), "deviceName": "Lagrange-deadbeefcafebabe"}
    )
    assert DEVICE_NAME.fullmatch(session.device_name)


def test_legacy_full_rizify_hash_is_migrated() -> None:
    old = "流转者-" + "a" * FULL_SHA256_HEX_LENGTH
    session = SessionStore.from_mapping({"guid": list(bytes(16)), "deviceName": old})
    assert DEVICE_NAME.fullmatch(session.device_name)


def test_custom_device_name_is_preserved() -> None:
    session = SessionStore.from_mapping({"guid": list(bytes(16)), "deviceName": "my-custom-device"})
    assert session.device_name == "my-custom-device"


def test_legacy_session_file_is_migrated_to_session_json(tmp_path: Path) -> None:
    legacy = tmp_path / "session-store.json"
    legacy.write_text(
        json.dumps(
            {
                "uin": 10001,
                "uid": "u_test",
                "guid": list(bytes(range(16))),
                "deviceName": "Lagrange-0123456789abcdef",
            }
        ),
        encoding="utf-8",
    )
    session = load_session(tmp_path, 10001)
    assert session.uid == "u_test"
    assert DEVICE_NAME.fullmatch(session.device_name)
    assert (tmp_path / "session.json").is_file()
    migrated = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert migrated["deviceName"] == session.device_name
