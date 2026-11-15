from __future__ import annotations

from dataclasses import dataclass

from .protobuf import (
    field_bytes,
    field_message,
    field_packed_varints,
    field_string,
    field_varint,
    fields_map,
    get_bytes,
    get_varint,
)

SELF_INFO_KEYS = [20002, 102, 20009, 103, 105, 20003, 20020, 20021, 20026, 20037, 27394]
FRIEND_INFO_KEYS = [102, 103, 20002, 27394, 20037, 20009]


def encode_oidb_envelope(
    command: int, service_type: int, body: bytes, *, reserved: bool = False
) -> bytes:
    value = (
        field_varint(1, command)
        + field_varint(2, service_type)
        + field_varint(3, 0)
        + field_bytes(4, body)
        + field_varint(5, 0)
    )
    if reserved:
        value += field_varint(12, 1)
    return value


def decode_oidb_envelope(payload: bytes) -> bytes:
    fields = fields_map(payload)
    error = get_varint(fields, 3)
    if error != 0:
        from .exceptions import ServiceError

        raise ServiceError("Oidb", error, get_bytes(fields, 5).decode(errors="replace"))
    return get_bytes(fields, 4)


@dataclass(slots=True)
class Friend:
    uin: int
    uid: str
    nickname: str = ""
    remark: str = ""
    bio: str = ""
    qid: str = ""
    age: int = 0
    gender: int = 0
    category_id: int = 0
    category_name: str = ""


@dataclass(slots=True)
class Group:
    uin: int
    name: str = ""
    member_count: int = 0
    capacity: int = 0
    remark: str = ""
    created_at: int = 0
    description: str = ""
    question: str = ""
    announcement_preview: str = ""
    owner_uid: str = ""


@dataclass(slots=True)
class GroupMember:
    uin: int
    uid: str
    nickname: str = ""
    card: str = ""
    special_title: str = ""
    level: int = 0
    joined_at: int = 0
    last_spoke_at: int = 0
    muted_until: int | None = None
    role: str = "member"


@dataclass(slots=True)
class UserInfo:
    uin: int
    uid: str = ""
    nickname: str = ""
    bio: str = ""
    gender: int = 0
    remark: str = ""
    level: int = 0
    country: str = ""
    city: str = ""
    school: str = ""
    register_time: int = 0
    age: int = 0
    qid: str = ""


def _parse_props(data: bytes) -> tuple[dict[int, int], dict[int, str]]:
    props = fields_map(data)
    numbers: dict[int, int] = {}
    strings: dict[int, str] = {}
    for entry in props.get(1, []):
        if not isinstance(entry.value, bytes):
            continue
        pair = fields_map(entry.value)
        numbers[get_varint(pair, 1)] = get_varint(pair, 2)
    for entry in props.get(2, []):
        if not isinstance(entry.value, bytes):
            continue
        pair = fields_map(entry.value)
        strings[get_varint(pair, 1)] = get_bytes(pair, 2).decode(errors="replace")
    return numbers, strings


def build_fetch_friends(next_uin: int | None) -> bytes:
    cookie = b"" if next_uin is None else field_message(1, field_varint(1, next_uin))
    biz1 = field_varint(1, 1) + field_message(2, field_packed_varints(1, FRIEND_INFO_KEYS))
    biz4 = field_varint(1, 4) + field_message(2, field_packed_varints(1, [100, 101, 102]))
    return encode_oidb_envelope(
        0xFD4,
        1,
        field_varint(2, 300)
        + field_message(5, cookie)
        + field_varint(6, 1)
        + field_message(10001, biz1)
        + field_message(10001, biz4),
    )


def parse_fetch_friends(payload: bytes) -> tuple[list[Friend], int | None]:
    categories: dict[int, str] = {}
    for item in fields_map(payload).get(102, []):
        if isinstance(item.value, bytes):
            category = fields_map(item.value)
            categories[get_varint(category, 1)] = get_bytes(category, 2).decode(errors="replace")
    friends: list[Friend] = []
    for item in fields_map(payload).get(101, []):
        if not isinstance(item.value, bytes):
            continue
        raw = fields_map(item.value)
        numbers: dict[int, int] = {}
        strings: dict[int, str] = {}
        for sub_item in raw.get(10001, []):
            if not isinstance(sub_item.value, bytes):
                continue
            sub = fields_map(sub_item.value)
            if get_varint(sub, 1) == 1:
                numbers, strings = _parse_props(get_bytes(sub, 2))
                break
        category_id = get_varint(raw, 2)
        friends.append(
            Friend(
                uin=get_varint(raw, 3),
                uid=get_bytes(raw, 1).decode(errors="replace"),
                nickname=strings.get(20002, ""),
                remark=strings.get(103, ""),
                bio=strings.get(102, ""),
                qid=strings.get(27394, ""),
                age=numbers.get(20037, 0),
                gender=numbers.get(20009, 0),
                category_id=category_id,
                category_name=categories.get(category_id, ""),
            )
        )
    cookie_fields = fields_map(payload).get(2)
    next_uin: int | None = None
    if cookie_fields and isinstance(cookie_fields[-1].value, bytes):
        cookie = fields_map(cookie_fields[-1].value)
        if 1 in cookie:
            next_uin = get_varint(cookie, 1)
    return friends, next_uin


def build_fetch_groups() -> bytes:
    config1_fields = [
        1,
        2,
        3,
        4,
        5,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        5001,
        5002,
        5003,
    ]
    config1 = b"".join(field_varint(number, 1) for number in config1_fields)
    config2 = b"".join(field_varint(number, 1) for number in range(1, 9))
    config3 = field_varint(5, 1) + field_varint(6, 1)
    body = field_message(
        1,
        field_message(1, config1) + field_message(2, config2) + field_message(3, config3),
    )
    return encode_oidb_envelope(0xFE5, 2, body)


def parse_fetch_groups(payload: bytes) -> list[Group]:
    groups: list[Group] = []
    for item in fields_map(payload).get(2, []):
        if not isinstance(item.value, bytes):
            continue
        raw = fields_map(item.value)
        info = fields_map(get_bytes(raw, 4))
        custom = fields_map(get_bytes(raw, 5))
        owner = fields_map(get_bytes(info, 1))
        groups.append(
            Group(
                uin=get_varint(raw, 3),
                name=get_bytes(info, 5).decode(errors="replace"),
                member_count=get_varint(info, 4),
                capacity=get_varint(info, 3),
                remark=get_bytes(custom, 3).decode(errors="replace"),
                created_at=get_varint(info, 2),
                description=get_bytes(info, 21).decode(errors="replace"),
                question=get_bytes(info, 19).decode(errors="replace"),
                announcement_preview=get_bytes(info, 30).decode(errors="replace"),
                owner_uid=get_bytes(owner, 2).decode(errors="replace"),
            )
        )
    return groups


def build_fetch_group_members(group_uin: int, cookie: bytes | None = None) -> bytes:
    member_fields = [10, 11, 12, 17, 100, 101, 102, 107]
    body = b"".join(field_varint(number, 1) for number in member_fields)
    request = (
        field_varint(1, group_uin)
        + field_varint(2, 5)
        + field_varint(3, 2)
        + field_message(4, body)
    )
    if cookie is not None:
        request += field_bytes(15, cookie)
    return encode_oidb_envelope(0xFE7, 3, request)


def parse_fetch_group_members(
    payload: bytes,
) -> tuple[list[GroupMember], bytes | None, int]:
    raw = fields_map(payload)
    members: list[GroupMember] = []
    for item in raw.get(2, []):
        if not isinstance(item.value, bytes):
            continue
        member = fields_map(item.value)
        identity = fields_map(get_bytes(member, 1))
        card = fields_map(get_bytes(member, 11))
        level = fields_map(get_bytes(member, 12))
        muted_values = member.get(102)
        role_id = get_varint(member, 107)
        members.append(
            GroupMember(
                uin=get_varint(identity, 4),
                uid=get_bytes(identity, 2).decode(errors="replace"),
                nickname=get_bytes(member, 10).decode(errors="replace"),
                card=get_bytes(card, 2).decode(errors="replace"),
                special_title=get_bytes(member, 17).decode(errors="replace"),
                level=get_varint(level, 2),
                joined_at=get_varint(member, 100),
                last_spoke_at=get_varint(member, 101),
                muted_until=(
                    int(muted_values[-1].value)
                    if muted_values and isinstance(muted_values[-1].value, int)
                    else None
                ),
                role={1: "owner", 2: "admin"}.get(role_id, "member"),
            )
        )
    cookie = get_bytes(raw, 15) or None
    return members, cookie, get_varint(raw, 3)


def build_fetch_user_info_uin(uin: int) -> bytes:
    body = field_varint(1, uin)
    for info_key in SELF_INFO_KEYS:
        body += field_message(3, field_varint(1, info_key))
    return encode_oidb_envelope(0xFE1, 2, body)


def build_fetch_user_info_uid(uid: str) -> bytes:
    body = field_string(1, uid)
    for info_key in SELF_INFO_KEYS:
        body += field_message(3, field_varint(1, info_key))
    return encode_oidb_envelope(0xFE1, 2, body)


def parse_user_info(payload: bytes) -> UserInfo:
    body = fields_map(get_bytes(fields_map(payload), 1))
    numbers, strings = _parse_props(get_bytes(body, 2))
    return UserInfo(
        uin=get_varint(body, 3),
        nickname=strings.get(20002, ""),
        bio=strings.get(102, ""),
        gender=numbers.get(20009, 0),
        remark=strings.get(103, ""),
        level=numbers.get(105, 0),
        country=strings.get(20003, ""),
        city=strings.get(20020, ""),
        school=strings.get(20021, ""),
        register_time=numbers.get(20026, 0),
        age=numbers.get(20037, 0),
        qid=strings.get(27394, ""),
    )
