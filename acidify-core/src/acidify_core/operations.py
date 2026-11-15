from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .protobuf import (
    field_bytes,
    field_message,
    field_string,
    field_varint,
    fields_map,
    get_bytes,
    get_varint,
)


@dataclass(slots=True)
class GroupFileEntry:
    file_id: str
    file_name: str
    parent_folder_id: str
    file_size: int
    expire_time: int
    modified_time: int
    uploader_uin: int
    uploaded_time: int
    downloaded_times: int


@dataclass(slots=True)
class GroupFolderEntry:
    folder_id: str
    parent_folder_id: str
    folder_name: str
    create_time: int
    modified_time: int
    creator_uin: int
    total_file_count: int


@dataclass(slots=True)
class GroupFileList:
    files: list[GroupFileEntry] = field(default_factory=list)
    folders: list[GroupFolderEntry] = field(default_factory=list)


@dataclass(slots=True)
class GroupNotification:
    notification_type: str
    group_id: int
    notification_seq: int
    state: str
    initiator_uin: int
    initiator_uid: str
    target_uin: int
    target_uid: str
    operator_uin: int | None
    operator_uid: str | None
    comment: str
    is_filtered: bool
    is_set: bool | None = None


@dataclass(slots=True)
class FriendRequest:
    time: int
    initiator_uin: int
    initiator_uid: str
    target_uin: int
    target_uid: str
    state: str
    comment: str
    via: str
    is_filtered: bool


@dataclass(slots=True)
class GroupAnnouncement:
    group_id: int
    announcement_id: str
    sender_id: int
    time: int
    content: str
    image_url: str | None
    show_edit_card: bool
    show_tip_window: bool
    confirm_required: bool
    is_pinned: bool
    show_to_new_member: bool


@dataclass(slots=True)
class EssenceMessage:
    group_id: int
    message_seq: int
    sender_id: int
    sender_name: str
    time: int
    segments: list[dict[str, Any]]


def _str(fields: dict[int, list[Any]], number: int) -> str:
    return get_bytes(fields, number).decode("utf-8", errors="replace")


def _nested(value: Any) -> bytes:
    return value if isinstance(value, bytes) else b""


def _request_state(value: int) -> str:
    return {1: "pending", 2: "accepted", 3: "rejected"}.get(value, "unknown")


def _friend_request_state(value: int) -> str:
    return {1: "pending", 3: "accepted", 7: "rejected"}.get(value, "unknown")


def build_fetch_friend_requests(*, self_uid: str, count: int, filtered: bool) -> bytes:
    if filtered:
        return field_varint(1, 1) + field_message(2, field_varint(1, count))
    return (
        field_varint(1, 1)
        + field_varint(3, 6)
        + field_string(4, self_uid)
        + field_varint(5, 0)
        + field_varint(6, count)
        + field_varint(8, 2)
        + field_varint(9, 0)
        + field_varint(12, 1)
        + field_varint(22, 1)
    )


def parse_friend_requests(payload: bytes, *, filtered: bool) -> list[dict[str, Any]]:
    if filtered:
        info = fields_map(get_bytes(fields_map(payload), 2))
        items = info.get(1, [])
        requests: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item.value, bytes):
                continue
            value = fields_map(item.value)
            requests.append(
                {
                    "source_uid": _str(value, 1),
                    "nickname": _str(value, 2),
                    "comment": _str(value, 5),
                    "via": _str(value, 6),
                    "warning": _str(value, 7),
                    "timestamp": get_varint(value, 8),
                    "state": "pending",
                }
            )
        return requests
    info = fields_map(get_bytes(fields_map(payload), 3))
    requests = []
    for item in info.get(7, []):
        if not isinstance(item.value, bytes):
            continue
        value = fields_map(item.value)
        requests.append(
            {
                "target_uid": _str(value, 1),
                "source_uid": _str(value, 2),
                "state": _friend_request_state(get_varint(value, 3)),
                "timestamp": get_varint(value, 4),
                "comment": _str(value, 5),
                "via": _str(value, 6),
                "source_id": get_varint(value, 7),
                "sub_source_id": get_varint(value, 8),
            }
        )
    return requests


def build_set_normal_friend_request(initiator_uid: str, accept: bool) -> bytes:
    return field_varint(1, 3 if accept else 5) + field_string(2, initiator_uid)


def build_set_filtered_friend_request(self_uid: str, initiator_uid: str) -> bytes:
    return field_string(1, self_uid) + field_string(2, initiator_uid)


def build_delete_friend(target_uid: str, block: bool) -> bytes:
    field3 = field_varint(1, 8) + field_varint(2, 8) + field_varint(3, 50)
    field2 = field_varint(1, 130) + field_varint(2, 109) + field_message(3, field3)
    body = (
        field_string(1, target_uid)
        + field_message(2, field2)
        + field_varint(3, 1 if block else 0)
        + field_varint(4, 0)
    )
    return field_message(1, body)


def build_profile_like(target_uid: str, count: int) -> bytes:
    return field_string(11, target_uid) + field_varint(12, 71) + field_varint(13, count)


def build_poke(*, target_uin: int, group_id: int = 0, friend_uin: int = 0) -> bytes:
    return (
        field_varint(1, target_uin)
        + field_varint(2, group_id)
        + field_varint(5, friend_uin)
        + field_varint(6, 0)
    )


def build_group_notifications_request(*, start_sequence: int, count: int) -> bytes:
    return field_varint(1, count) + field_varint(2, start_sequence)


def parse_group_notifications(
    payload: bytes, *, filtered: bool
) -> tuple[list[dict[str, Any]], int]:
    response = fields_map(payload)
    next_sequence = get_varint(response, 2)
    values: list[dict[str, Any]] = []
    for item in response.get(1, []):
        if not isinstance(item.value, bytes):
            continue
        value = fields_map(item.value)
        group = fields_map(get_bytes(value, 4))
        user1 = fields_map(get_bytes(value, 5))
        user2_fields = get_bytes(value, 6)
        user3_fields = get_bytes(value, 7)
        user2 = fields_map(user2_fields) if user2_fields else {}
        user3 = fields_map(user3_fields) if user3_fields else {}
        notify_type = get_varint(value, 2)
        values.append(
            {
                "notify_type": notify_type,
                "sequence": get_varint(value, 1),
                "state": _request_state(get_varint(value, 3)),
                "group_id": get_varint(group, 1),
                "group_name": _str(group, 2),
                "user1_uid": _str(user1, 1),
                "user1_nickname": _str(user1, 2),
                "user2_uid": _str(user2, 1) if user2 else None,
                "user2_nickname": _str(user2, 2) if user2 else None,
                "user3_uid": _str(user3, 1) if user3 else None,
                "time": get_varint(value, 8),
                "comment": _str(value, 10),
                "is_filtered": filtered,
            }
        )
    return values, next_sequence


def normalize_group_notification(
    value: dict[str, Any], uins: dict[str, int]
) -> GroupNotification | None:
    notify_type = value["notify_type"]
    user1_uid = value["user1_uid"]
    user2_uid = value.get("user2_uid")
    user3_uid = value.get("user3_uid")
    user1_uin = uins.get(user1_uid, 0)
    user2_uin = uins.get(user2_uid, 0) if user2_uid else None
    user3_uin = uins.get(user3_uid, 0) if user3_uid else None
    common = {
        "group_id": value["group_id"],
        "notification_seq": value["sequence"],
        "state": value["state"],
        "is_filtered": value["is_filtered"],
        "comment": value["comment"],
    }
    if notify_type == 1:
        return GroupNotification(
            notification_type="join_request",
            initiator_uin=user1_uin,
            initiator_uid=user1_uid,
            target_uin=user1_uin,
            target_uid=user1_uid,
            operator_uin=user2_uin,
            operator_uid=user2_uid,
            **common,
        )
    if notify_type in (3, 16):
        return GroupNotification(
            notification_type="admin_change",
            initiator_uin=user2_uin or 0,
            initiator_uid=user2_uid or "",
            target_uin=user1_uin,
            target_uid=user1_uid,
            operator_uin=user2_uin,
            operator_uid=user2_uid,
            is_set=notify_type == 3,
            **common,
        )
    if notify_type == 6:
        operator_uid = user2_uid or user3_uid
        operator_uin = user2_uin or user3_uin
        return GroupNotification(
            notification_type="kick",
            initiator_uin=operator_uin or 0,
            initiator_uid=operator_uid or "",
            target_uin=user1_uin,
            target_uid=user1_uid,
            operator_uin=operator_uin,
            operator_uid=operator_uid,
            **common,
        )
    if notify_type == 13:
        return GroupNotification(
            notification_type="quit",
            initiator_uin=user1_uin,
            initiator_uid=user1_uid,
            target_uin=user1_uin,
            target_uid=user1_uid,
            operator_uin=None,
            operator_uid=None,
            **common,
        )
    if notify_type == 22:
        return GroupNotification(
            notification_type="invited_join_request",
            initiator_uin=user2_uin or 0,
            initiator_uid=user2_uid or "",
            target_uin=user1_uin,
            target_uid=user1_uid,
            operator_uin=user3_uin,
            operator_uid=user3_uid,
            **common,
        )
    return None


def build_set_group_request(
    *,
    group_id: int,
    sequence: int,
    event_type: int,
    accept: bool,
    reason: str,
) -> bytes:
    body = (
        field_varint(1, sequence)
        + field_varint(2, event_type)
        + field_varint(3, group_id)
        + field_string(4, reason)
    )
    return field_varint(1, 1 if accept else 2) + field_message(2, body)


def build_set_group_name(group_id: int, name: str) -> bytes:
    return field_varint(1, group_id) + field_string(2, name)


def build_set_group_whole_mute(group_id: int, mute: bool) -> bytes:
    return field_varint(1, group_id) + field_message(
        2, field_varint(17, 0xFFFFFFFFFFFFFFFF if mute else 0)
    )


def _member_info(uid: str, field_number: int, value: bytes, extra: bytes = b"") -> bytes:
    info = field_string(1, uid) + field_bytes(field_number, value) + extra
    return field_message(3, info)


def build_set_member_card(group_id: int, uid: str, card: str) -> bytes:
    return field_varint(1, group_id) + _member_info(uid, 8, card.encode())


def build_set_member_title(group_id: int, uid: str, title: str) -> bytes:
    base = field_varint(1, group_id)
    info = (
        field_string(1, uid) + field_bytes(5, title.encode()) + field_varint(6, 0xFFFFFFFFFFFFFFFF)
    )
    return base + field_message(3, info)


def build_set_member_admin(group_id: int, uid: str, is_admin: bool) -> bytes:
    return field_varint(1, group_id) + field_string(2, uid) + field_varint(3, 1 if is_admin else 0)


def build_set_member_mute(group_id: int, uid: str, duration: int) -> bytes:
    return (
        field_varint(1, group_id)
        + field_varint(2, 1)
        + field_message(3, field_string(1, uid) + field_varint(2, duration))
    )


def build_kick_member(group_id: int, uid: str, reject_add_request: bool, reason: str) -> bytes:
    return (
        field_varint(1, group_id)
        + field_varint(2, 0)
        + field_string(3, uid)
        + field_varint(4, 1 if reject_add_request else 0)
        + field_string(5, reason)
    )


def build_quit_group(group_id: int) -> bytes:
    return field_varint(1, group_id)


def build_essence_set(group_id: int, sequence: int, random: int) -> bytes:
    return field_varint(1, group_id) + field_varint(2, sequence) + field_varint(3, random)


def build_group_reaction(group_id: int, sequence: int, code: str, reaction_type: int) -> bytes:
    return (
        field_varint(2, group_id)
        + field_varint(3, sequence)
        + field_string(4, code)
        + field_varint(5, reaction_type)
    )


def build_group_file_list(group_id: int, directory: str, start_index: int, count: int) -> bytes:
    body = (
        field_varint(1, group_id)
        + field_varint(2, 7)
        + field_string(3, directory)
        + field_varint(5, count)
        + field_varint(9, 1)
        + field_varint(13, start_index)
        + field_varint(17, 2)
        + field_varint(18, 0)
    )
    return field_message(2, body)


def parse_group_file_list(
    payload: bytes,
) -> tuple[list[GroupFileEntry], list[GroupFolderEntry], bool]:
    body = fields_map(get_bytes(fields_map(payload), 2))
    ret = get_varint(body, 1)
    if ret != 0:
        raise ValueError(f"群文件列表返回 {ret}")
    files: list[GroupFileEntry] = []
    folders: list[GroupFolderEntry] = []
    for item in body.get(5, []):
        if not isinstance(item.value, bytes):
            continue
        value = fields_map(item.value)
        item_type = get_varint(value, 1)
        if item_type == 1:
            info = fields_map(get_bytes(value, 3))
            files.append(
                GroupFileEntry(
                    file_id=_str(info, 1),
                    file_name=_str(info, 2),
                    parent_folder_id=_str(info, 16),
                    file_size=get_varint(info, 3),
                    expire_time=get_varint(info, 7),
                    modified_time=get_varint(info, 8),
                    uploader_uin=get_varint(info, 15),
                    uploaded_time=get_varint(info, 6),
                    downloaded_times=get_varint(info, 9),
                )
            )
        elif item_type == 2:
            info = fields_map(get_bytes(value, 2))
            folders.append(
                GroupFolderEntry(
                    folder_id=_str(info, 1),
                    parent_folder_id=_str(info, 2),
                    folder_name=_str(info, 3),
                    create_time=get_varint(info, 4),
                    modified_time=get_varint(info, 5),
                    creator_uin=get_varint(info, 6),
                    total_file_count=get_varint(info, 8),
                )
            )
    return files, folders, get_varint(body, 4) != 0


def build_group_file_download(group_id: int, file_id: str) -> bytes:
    body = (
        field_varint(1, group_id)
        + field_varint(2, 7)
        + field_varint(3, 102)
        + field_string(4, file_id)
    )
    return field_message(3, body)


def parse_group_file_download(payload: bytes) -> str:
    body = fields_map(get_bytes(fields_map(payload), 3))
    dns = _str(body, 5)
    encoded = get_bytes(body, 6).hex()
    if not dns or not encoded:
        raise ValueError("群文件下载地址为空")
    return f"https://{dns}/ftn_handler/{encoded}/?fname="


def build_group_file_delete(group_id: int, file_id: str) -> bytes:
    body = (
        field_varint(1, group_id)
        + field_varint(2, 7)
        + field_varint(3, 102)
        + field_string(4, "/")
        + field_string(5, file_id)
    )
    return field_message(4, body)


def build_group_file_rename(
    group_id: int,
    file_id: str,
    parent_folder_id: str,
    new_name: str,
) -> bytes:
    body = (
        field_varint(1, group_id)
        + field_varint(2, 7)
        + field_varint(3, 102)
        + field_string(4, file_id)
        + field_string(5, parent_folder_id)
        + field_string(6, new_name)
    )
    return field_message(5, body)


def build_group_file_move(
    group_id: int,
    file_id: str,
    parent_folder_id: str,
    target_folder_id: str,
) -> bytes:
    body = (
        field_varint(1, group_id)
        + field_varint(2, 7)
        + field_varint(3, 102)
        + field_string(4, file_id)
        + field_string(5, parent_folder_id)
        + field_string(6, target_folder_id)
    )
    return field_message(6, body)


def parse_group_file_mutation(payload: bytes, field_number: int) -> None:
    body = fields_map(get_bytes(fields_map(payload), field_number))
    ret = get_varint(body, 1)
    if ret != 0:
        raise ValueError(_str(body, 2) or f"群文件操作返回 {ret}")


def build_group_file_folder_create(group_id: int, name: str) -> bytes:
    body = field_varint(1, group_id) + field_string(3, "/") + field_string(4, name)
    return field_message(1, body)


def parse_group_folder_create(payload: bytes) -> str:
    body = fields_map(get_bytes(fields_map(payload), 1))
    ret = get_varint(body, 1)
    if ret != 0:
        raise ValueError(_str(body, 2) or f"创建群文件夹返回 {ret}")
    return _str(body, 3)


def build_group_folder_delete(group_id: int, folder_id: str) -> bytes:
    return field_message(2, field_varint(1, group_id) + field_string(3, folder_id))


def build_group_folder_rename(group_id: int, folder_id: str, name: str) -> bytes:
    return field_message(
        3,
        field_varint(1, group_id) + field_string(3, folder_id) + field_string(4, name),
    )


def parse_group_folder_mutation(payload: bytes, field_number: int) -> None:
    body = fields_map(get_bytes(fields_map(payload), field_number))
    ret = get_varint(body, 1)
    if ret != 0:
        raise ValueError(_str(body, 2) or f"群文件夹操作返回 {ret}")


def build_persist_group_file(group_id: int, file_id: str) -> bytes:
    body = field_varint(1, group_id) + field_varint(3, 102) + field_string(4, file_id)
    return field_message(1, body)


def build_broadcast_group_file(group_id: int, file_id: str, random_id: int) -> bytes:
    info = (
        field_varint(1, 102)
        + field_string(2, file_id)
        + field_varint(3, random_id)
        + field_string(4, "")
        + field_varint(5, 1)
    )
    body = field_varint(1, group_id) + field_varint(2, 2) + field_message(3, info)
    return field_message(5, body)


def build_profile_settings(*, nickname: str | None, bio: str | None) -> bytes:
    value = b""
    if nickname is not None:
        value += field_message(2, field_varint(1, 20002) + field_string(2, nickname))
    if bio is not None:
        value += field_message(2, field_varint(1, 102) + field_string(2, bio))
    return value


def parse_profile_settings(payload: bytes) -> None:
    ret = get_varint(fields_map(payload), 1)
    if ret != 0:
        raise ValueError(f"资料设置返回 {ret}")


def build_pinned_chats_request() -> bytes:
    return b""


def parse_pinned_chats(payload: bytes) -> tuple[list[str], list[int]]:
    fields = fields_map(payload)
    friend_uids = [_str(fields_map(_nested(value)), 1) for value in fields.get(1, []) if value]
    group_uins = [get_varint(fields_map(_nested(value)), 1) for value in fields.get(3, []) if value]
    return [item for item in friend_uids if item], [item for item in group_uins if item]


def build_set_friend_pin(friend_uid: str, is_pinned: bool, timestamp: int) -> bytes:
    stamp = timestamp.to_bytes(4, "big", signed=True) if is_pinned else b""
    info = field_string(1, friend_uid) + field_message(
        400, field_varint(1, 13578) + field_bytes(2, stamp)
    )
    return field_varint(1, 0) + field_message(2, info) + field_varint(3, 1)


def build_set_group_pin(group_id: int, is_pinned: bool, timestamp: int) -> bytes:
    stamp = timestamp.to_bytes(4, "big", signed=True) if is_pinned else b""
    info = field_varint(2, group_id) + field_message(
        400, field_varint(1, 13569) + field_bytes(2, stamp)
    )
    return field_varint(1, 0) + field_message(2, info) + field_varint(3, 11)


def build_custom_faces_request(uin: int) -> bytes:
    platform_info = field_varint(1, 1) + field_string(2, "") + field_string(3, "")
    return (
        field_message(1, platform_info)
        + field_varint(2, uin)
        + field_varint(3, 1)
        + field_varint(6, 1)
    )


def parse_custom_faces(payload: bytes, uin: int) -> list[str]:
    fields = fields_map(payload)
    ret = get_varint(fields, 1)
    if ret != 0:
        raise ValueError(_str(fields, 2) or f"收藏表情返回 {ret}")
    user_info = fields_map(get_bytes(fields, 4))
    files = [
        _nested(value).decode("utf-8", errors="replace") for value in user_info.get(1, []) if value
    ]
    bid = _str(user_info, 3)
    return [f"https://p.qpic.cn/{bid}/{uin}/{name}/0" for name in files]


def build_pskey_request(domains: list[str]) -> bytes:
    return b"".join(field_string(1, domain) for domain in domains)


def parse_pskey_response(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in fields_map(payload).get(1, []):
        entry = fields_map(_nested(value))
        domain = _str(entry, 1)
        key = _str(entry, 2)
        if domain:
            result[domain] = key
    return result
