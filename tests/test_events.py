from __future__ import annotations

import struct

import pytest
from acidify_core.events import parse_push_events
from acidify_core.protobuf import (
    field_message,
    field_string,
    field_varint,
)


def _payload(
    push_type: int,
    sub_type: int,
    content: bytes,
    *,
    from_uin: int = 0,
) -> bytes:
    routing = field_varint(1, from_uin) if from_uin else b""
    content_head = field_varint(1, push_type) + field_varint(2, sub_type)
    message_body = field_message(2, content)
    common = (
        field_message(1, routing) + field_message(2, content_head) + field_message(3, message_body)
    )
    return field_message(1, common)


def _group_wrapper(group_id: int, body: bytes) -> bytes:
    return struct.pack(">I", group_id) + b"\x00\x00\x00" + body


async def _resolve(uid: str) -> int:
    return {"uid-a": 1001, "uid-b": 1002, "uid-op": 9000}[uid]


@pytest.mark.asyncio
async def test_friend_request_push_event() -> None:
    body = field_string(2, "uid-a") + field_string(10, "hello") + field_string(11, "search")
    payload = _payload(0x210, 35, field_message(1, body), from_uin=1001)

    events = await parse_push_events(payload, 1, _resolve, now=1700000000)

    assert events == [
        {
            "event_type": "friend_request",
            "time": 1700000000,
            "self_id": 1,
            "data": {
                "initiator_id": 1001,
                "initiator_uid": "uid-a",
                "comment": "hello",
                "via": "search",
            },
        }
    ]


@pytest.mark.asyncio
async def test_group_mute_push_event_resolves_target() -> None:
    state = field_string(1, "uid-b") + field_varint(2, 600)
    content = (
        field_varint(1, 42) + field_string(4, "uid-op") + field_message(5, field_message(3, state))
    )
    payload = _payload(0x2DC, 12, content)

    events = await parse_push_events(payload, 1, _resolve, now=1700000000)

    assert events[0]["event_type"] == "group_mute"
    assert events[0]["data"] == {
        "group_id": 42,
        "user_id": 1002,
        "operator_id": 9000,
        "duration": 600,
    }


@pytest.mark.asyncio
async def test_group_recall_push_event_uses_wrapper_group_id() -> None:
    recalled = field_varint(1, 321) + field_string(6, "uid-b")
    recall = (
        field_string(1, "uid-op")
        + field_message(3, recalled)
        + field_message(9, field_string(2, "撤回了一条消息"))
    )
    body = field_message(11, recall)
    payload = _payload(0x2DC, 17, _group_wrapper(42, body))

    events = await parse_push_events(payload, 1, _resolve, now=1700000000)

    assert events == [
        {
            "event_type": "message_recall",
            "time": 1700000000,
            "self_id": 1,
            "data": {
                "message_scene": "group",
                "peer_id": 42,
                "message_seq": 321,
                "sender_id": 1002,
                "operator_id": 9000,
                "display_suffix": "撤回了一条消息",
            },
        }
    ]
