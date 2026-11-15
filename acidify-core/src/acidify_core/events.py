from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from .protobuf import ProtoField, fields_map, get_bytes, get_varint

MESSAGE_PUSH_TYPES = frozenset({82, 166, 208, 529})

UinResolver = Callable[[str], Awaitable[int]]


def _text(fields: dict[int, list[ProtoField]], number: int) -> str:
    return get_bytes(fields, number).decode(errors="replace")


def _message(event_type: str, self_id: int, data: dict[str, Any], now: int) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "time": now,
        "self_id": self_id,
        "data": data,
    }


def _map_entries(value: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in fields_map(value).get(1, []):
        if not isinstance(field.value, bytes):
            continue
        entry = fields_map(field.value)
        result[_text(entry, 1)] = _text(entry, 2)
    return result


def _gray_tip(value: bytes) -> tuple[int, dict[str, str]]:
    fields = fields_map(value)
    params: dict[str, str] = {}
    for field in fields.get(7, []):
        if isinstance(field.value, bytes):
            params.update(_map_entries(field.value))
    return get_varint(fields, 1), params


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


class _PushEventParser:
    def __init__(self, self_id: int, resolve_uin: UinResolver, now: int) -> None:
        self.self_id = self_id
        self.resolve_uin = resolve_uin
        self.now = now

    async def _uin(self, uid: str) -> int:
        if not uid:
            return 0
        try:
            return await self.resolve_uin(uid)
        except Exception:
            return 0

    async def parse(self, payload: bytes) -> list[dict[str, Any]]:
        push = fields_map(payload)
        common = fields_map(get_bytes(push, 1))
        routing = fields_map(get_bytes(common, 1))
        content_head = fields_map(get_bytes(common, 2))
        message_body = fields_map(get_bytes(common, 3))
        push_type = get_varint(content_head, 1)
        sub_type = get_varint(content_head, 2)
        content = get_bytes(message_body, 2)
        if not content or push_type in MESSAGE_PUSH_TYPES:
            return []
        if push_type == 0x210:
            return await self._friend_event(sub_type, routing, content)
        if push_type == 0x2DC:
            return await self._group_event(sub_type, content)
        if push_type in (33, 34):
            return await self._group_member_change(push_type, content)
        if push_type == 44:
            return await self._group_admin_change(content)
        if push_type == 84:
            return await self._group_join_request(content)
        if push_type == 525:
            return await self._group_invited_join_request(content)
        return []

    async def _friend_event(
        self,
        sub_type: int,
        routing: dict[int, list[ProtoField]],
        content: bytes,
    ) -> list[dict[str, Any]]:
        if sub_type == 35:
            return await self._friend_request(routing, content)
        if sub_type == 290:
            return await self._friend_nudge(routing, content)
        if sub_type in (138, 139):
            return await self._friend_recall(content)
        if sub_type == 39:
            return await self._friend_pin_change(content)
        return []

    async def _friend_request(
        self, routing: dict[int, list[ProtoField]], content: bytes
    ) -> list[dict[str, Any]]:
        root = fields_map(content)
        body = fields_map(get_bytes(root, 1))
        via = _text(body, 11)
        if not via:
            via_body = fields_map(get_bytes(root, 1))
            via = _text(fields_map(get_bytes(via_body, 1)), 5)
        return [
            _message(
                "friend_request",
                self.self_id,
                {
                    "initiator_id": get_varint(routing, 1),
                    "initiator_uid": _text(body, 2),
                    "comment": _text(body, 10),
                    "via": via,
                },
                self.now,
            )
        ]

    async def _friend_nudge(
        self, routing: dict[int, list[ProtoField]], content: bytes
    ) -> list[dict[str, Any]]:
        biz_type, params = _gray_tip(content)
        if biz_type != 12:
            return []
        uin1 = _safe_int(params.get("uin_str1", "0"))
        uin2 = _safe_int(params.get("uin_str2", "0"))
        return [
            _message(
                "friend_nudge",
                self.self_id,
                {
                    "user_id": get_varint(routing, 1),
                    "is_self_send": uin1 == self.self_id,
                    "is_self_receive": uin2 == self.self_id,
                    "display_action": params.get("action_str") or params.get("alt_str1", ""),
                    "display_suffix": params.get("suffix_str", ""),
                    "display_action_img_url": params.get("action_img_url", ""),
                },
                self.now,
            )
        ]

    async def _friend_recall(self, content: bytes) -> list[dict[str, Any]]:
        body = fields_map(get_bytes(fields_map(content), 1))
        from_uid = _text(body, 1)
        from_uin = await self._uin(from_uid)
        suffix = _text(fields_map(get_bytes(body, 13)), 2)
        return [
            _message(
                "message_recall",
                self.self_id,
                {
                    "message_scene": "friend",
                    "peer_id": from_uin,
                    "message_seq": get_varint(body, 20),
                    "sender_id": from_uin,
                    "operator_id": from_uin,
                    "display_suffix": suffix,
                },
                self.now,
            )
        ]

    async def _friend_pin_change(self, content: bytes) -> list[dict[str, Any]]:
        root = fields_map(content)
        pin = fields_map(get_bytes(fields_map(get_bytes(root, 1)), 20))
        body = fields_map(get_bytes(pin, 1))
        uid = _text(body, 1)
        group_id = get_varint(body, 2, -1)
        if group_id >= 0:
            scene = "group"
            peer_id = group_id
        else:
            scene = "friend"
            peer_id = await self._uin(uid)
        if peer_id == 0:
            return []
        is_pinned = bool(get_bytes(fields_map(get_bytes(body, 400)), 2))
        return [
            _message(
                "peer_pin_change",
                self.self_id,
                {
                    "message_scene": scene,
                    "peer_id": peer_id,
                    "is_pinned": is_pinned,
                },
                self.now,
            )
        ]

    async def _group_event(self, sub_type: int, content: bytes) -> list[dict[str, Any]]:
        if sub_type == 12:
            return await self._group_mute(content)
        if sub_type == 20:
            return await self._group_nudge(content)
        if sub_type == 21:
            return self._group_essence_change(content)
        if sub_type == 17:
            return await self._group_recall(content)
        if sub_type == 16:
            return await self._group_subtype_16(content)
        return []

    def _group_wrapper(self, content: bytes) -> tuple[int, dict[int, list[ProtoField]]]:
        if len(content) < 7:
            raise ValueError("群事件外层长度不足")
        group_id = int.from_bytes(content[:4], "big")
        return group_id, fields_map(content[7:])

    async def _group_mute(self, content: bytes) -> list[dict[str, Any]]:
        root = fields_map(content)
        group_id = get_varint(root, 1)
        operator_id = await self._uin(_text(root, 4))
        state = fields_map(get_bytes(fields_map(get_bytes(root, 5)), 3))
        duration = get_varint(state, 2)
        target_uid = _text(state, 1)
        if target_uid:
            return [
                _message(
                    "group_mute",
                    self.self_id,
                    {
                        "group_id": group_id,
                        "user_id": await self._uin(target_uid),
                        "operator_id": operator_id,
                        "duration": duration,
                    },
                    self.now,
                )
            ]
        return [
            _message(
                "group_whole_mute",
                self.self_id,
                {
                    "group_id": group_id,
                    "operator_id": operator_id,
                    "is_mute": duration != 0,
                },
                self.now,
            )
        ]

    async def _group_nudge(self, content: bytes) -> list[dict[str, Any]]:
        outer_group, body = self._group_wrapper(content)
        biz_type, params = _gray_tip(get_bytes(body, 26))
        if biz_type != 12:
            return []
        sender = _safe_int(params.get("uin_str1", "0"))
        receiver = _safe_int(params.get("uin_str2", "0"))
        return [
            _message(
                "group_nudge",
                self.self_id,
                {
                    "group_id": get_varint(body, 4) or outer_group,
                    "sender_id": sender,
                    "receiver_id": receiver,
                    "display_action": params.get("action_str") or params.get("alt_str1", ""),
                    "display_suffix": params.get("suffix_str", ""),
                    "display_action_img_url": params.get("action_img_url", ""),
                },
                self.now,
            )
        ]

    def _group_essence_change(self, content: bytes) -> list[dict[str, Any]]:
        _, body = self._group_wrapper(content)
        essence = fields_map(get_bytes(body, 33))
        return [
            _message(
                "group_essence_message_change",
                self.self_id,
                {
                    "group_id": get_varint(essence, 1),
                    "message_seq": get_varint(essence, 2),
                    "operator_id": get_varint(essence, 6),
                    "is_set": get_varint(essence, 4) == 1,
                },
                self.now,
            )
        ]

    async def _group_recall(self, content: bytes) -> list[dict[str, Any]]:
        outer_group, body = self._group_wrapper(content)
        recall = fields_map(get_bytes(body, 11))
        group_id = get_varint(body, 4) or outer_group
        operator_id = await self._uin(_text(recall, 1))
        suffix = _text(fields_map(get_bytes(recall, 9)), 2)
        events: list[dict[str, Any]] = []
        for field in recall.get(3, []):
            if not isinstance(field.value, bytes):
                continue
            item = fields_map(field.value)
            author_id = await self._uin(_text(item, 6))
            events.append(
                _message(
                    "message_recall",
                    self.self_id,
                    {
                        "message_scene": "group",
                        "peer_id": group_id,
                        "message_seq": get_varint(item, 1),
                        "sender_id": author_id,
                        "operator_id": operator_id,
                        "display_suffix": suffix,
                    },
                    self.now,
                )
            )
        return events

    async def _group_subtype_16(self, content: bytes) -> list[dict[str, Any]]:
        outer_group, body = self._group_wrapper(content)
        field13 = get_varint(body, 13)
        if field13 == 35:
            group_id = get_varint(body, 4) or outer_group
            middle = fields_map(
                get_bytes(fields_map(get_bytes(fields_map(get_bytes(body, 44)), 1)), 1)
            )
            target = fields_map(get_bytes(middle, 2))
            data = fields_map(get_bytes(middle, 3))
            return [
                _message(
                    "group_message_reaction",
                    self.self_id,
                    {
                        "group_id": group_id,
                        "user_id": await self._uin(_text(data, 4)),
                        "message_seq": get_varint(target, 1),
                        "face_id": _text(data, 1),
                        "reaction_type": "emoji" if get_varint(data, 2) == 2 else "face",
                        "is_add": get_varint(data, 5) == 1,
                    },
                    self.now,
                )
            ]
        if field13 == 12:
            name = _text(fields_map(get_bytes(body, 5)), 2)
            return [
                _message(
                    "group_name_change",
                    self.self_id,
                    {
                        "group_id": get_varint(body, 4) or outer_group,
                        "new_group_name": name,
                        "operator_id": await self._uin(_text(body, 21)),
                    },
                    self.now,
                )
            ]
        return []

    async def _group_member_change(self, push_type: int, content: bytes) -> list[dict[str, Any]]:
        root = fields_map(content)
        group_id = get_varint(root, 1)
        member_uid = _text(root, 3)
        change_type = get_varint(root, 4)
        operator_uid = _text(fields_map(get_bytes(root, 5)), 1)
        member_id = await self._uin(member_uid)
        operator_id = await self._uin(operator_uid) if operator_uid else None
        if push_type == 33:
            return [
                _message(
                    "group_member_increase",
                    self.self_id,
                    {
                        "group_id": group_id,
                        "user_id": member_id,
                        "operator_id": operator_id if change_type == 130 else None,
                        "invitor_id": operator_id if change_type == 131 else None,
                    },
                    self.now,
                )
            ]
        if change_type == 129 and operator_id is not None:
            return [
                _message(
                    "group_disband",
                    self.self_id,
                    {"group_id": group_id, "operator_id": operator_id},
                    self.now,
                )
            ]
        return [
            _message(
                "group_member_decrease",
                self.self_id,
                {
                    "group_id": group_id,
                    "user_id": member_id,
                    "operator_id": operator_id,
                },
                self.now,
            )
        ]

    async def _group_admin_change(self, content: bytes) -> list[dict[str, Any]]:
        root = fields_map(content)
        group_id = get_varint(root, 1)
        body = fields_map(get_bytes(root, 4))
        set_info = fields_map(get_bytes(body, 2))
        unset_info = fields_map(get_bytes(body, 1))
        target_uid = _text(set_info, 1) or _text(unset_info, 1)
        if not target_uid:
            return []
        return [
            _message(
                "group_admin_change",
                self.self_id,
                {
                    "group_id": group_id,
                    "user_id": await self._uin(target_uid),
                    "operator_id": 0,
                    "is_set": bool(set_info),
                },
                self.now,
            )
        ]

    async def _group_join_request(self, content: bytes) -> list[dict[str, Any]]:
        root = fields_map(content)
        return [
            _message(
                "group_join_request",
                self.self_id,
                {
                    "group_id": get_varint(root, 1),
                    "notification_seq": 0,
                    "is_filtered": False,
                    "initiator_id": await self._uin(_text(root, 3)),
                    "comment": "",
                },
                self.now,
            )
        ]

    async def _group_invited_join_request(self, content: bytes) -> list[dict[str, Any]]:
        root = fields_map(content)
        if get_varint(root, 1) != 87:
            return []
        inner = fields_map(get_bytes(fields_map(get_bytes(root, 2)), 1))
        return [
            _message(
                "group_invited_join_request",
                self.self_id,
                {
                    "group_id": get_varint(inner, 1),
                    "notification_seq": 0,
                    "initiator_id": await self._uin(_text(inner, 6)),
                    "target_user_id": await self._uin(_text(inner, 5)),
                },
                self.now,
            )
        ]


async def parse_push_events(
    payload: bytes,
    self_id: int,
    resolve_uin: UinResolver,
    *,
    now: int | None = None,
) -> list[dict[str, Any]]:
    return await _PushEventParser(
        self_id, resolve_uin, int(time.time()) if now is None else now
    ).parse(payload)
