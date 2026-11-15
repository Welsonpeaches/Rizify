from __future__ import annotations

import base64
import gzip
import json
import re
import time
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .protobuf import (
    field_bytes,
    field_message,
    field_string,
    field_varint,
    fields_map,
    get_bytes,
    get_varint,
)

if TYPE_CHECKING:
    from .bot import Bot


@dataclass(slots=True)
class ParsedMessage:
    scene: str
    peer_id: int
    sequence: int
    sender_id: int
    sender_uid: str
    sender_name: str
    timestamp: int
    random: int
    segments: list[dict[str, Any]]
    raw: bytes


@dataclass(slots=True)
class HistoryResult:
    messages: list[ParsedMessage]
    next_sequence: int | None


@dataclass(slots=True)
class ForwardedNode:
    sequence: int
    sender_name: str
    avatar_url: str
    timestamp: int
    segments: list[dict[str, Any]] = field(default_factory=list)


def _entry(fields: dict[int, list[Any]], number: int) -> bytes:
    return get_bytes(fields, number)


def _string(fields: dict[int, list[Any]], number: int) -> str:
    return _entry(fields, number).decode("utf-8", errors="replace")


def _bool(fields: dict[int, list[Any]], number: int) -> bool:
    return get_varint(fields, number) != 0


def parse_common_message(
    raw: bytes,
    *,
    scene: str,
    peer_id: int,
) -> ParsedMessage:
    common = fields_map(raw)
    routing = fields_map(_entry(common, 1))
    content = fields_map(_entry(common, 2))
    body = fields_map(_entry(common, 3))
    rich = fields_map(_entry(body, 1))

    group = fields_map(_entry(routing, 8))
    c2c = fields_map(_entry(routing, 7))
    sender_uid = _string(routing, 2)
    sender_id = get_varint(routing, 1)
    sender_name = _string(group, 4) or _string(c2c, 6)
    segments: list[dict[str, Any]] = []
    elems = [element.value for element in rich.get(2, []) if isinstance(element.value, bytes)]
    index = 0
    while index < len(elems):
        segment, consumed = parse_elem(elems, index, scene=scene)
        index += consumed
        if segment is not None:
            segments.append(segment)

    return ParsedMessage(
        scene=scene,
        peer_id=peer_id,
        sequence=get_varint(content, 5),
        sender_id=sender_id,
        sender_uid=sender_uid,
        sender_name=sender_name,
        timestamp=get_varint(content, 6),
        random=get_varint(content, 4),
        segments=segments,
        raw=raw,
    )


def parse_elem(
    elems: list[bytes],
    index: int,
    *,
    scene: str,
) -> tuple[dict[str, Any] | None, int]:
    elem = fields_map(elems[index])

    if 1 in elem:
        text_fields = fields_map(get_bytes(elem, 1))
        text = _string(text_fields, 1)
        reserve = get_bytes(text_fields, 12)
        if reserve:
            attr = fields_map(reserve)
            at_type = get_varint(attr, 3)
            if at_type == 1:
                return {"type": "mention_all", "data": {}}, 1
            if at_type == 2:
                mention_uid = _string(attr, 9)
                return (
                    {
                        "type": "mention",
                        "data": {
                            "user_id": get_varint(attr, 4),
                            "name": text.removeprefix("@"),
                            "_uid": mention_uid,
                        },
                    },
                    1,
                )
        return {"type": "text", "data": {"text": text}}, 1

    if 2 in elem:
        face = fields_map(get_bytes(elem, 2))
        return (
            {
                "type": "face",
                "data": {
                    "face_id": str(get_varint(face, 1)),
                    "is_large": False,
                },
            },
            1,
        )

    if 45 in elem:
        consumed = 1
        while index + consumed < len(elems) and consumed < 4:
            next_fields = fields_map(elems[index + consumed])
            if 37 in next_fields:
                consumed += 1
                continue
            if 1 in next_fields:
                text_fields = fields_map(get_bytes(next_fields, 1))
                if get_bytes(text_fields, 12):
                    consumed += 1
                    continue
            break
        return (
            _parse_reply(fields_map(get_bytes(elem, 45)), scene=scene),
            consumed,
        )

    if 53 in elem:
        common = fields_map(get_bytes(elem, 53))
        service_type = get_varint(common, 1)
        business_type = get_varint(common, 3)
        payload = get_bytes(common, 2)
        if service_type in (10, 20, 48):
            if business_type in (10, 20):
                return _parse_media_message(payload, "image"), 1
            if business_type in (12, 22):
                return _parse_media_message(payload, "record"), 1
            if business_type in (11, 21):
                return _parse_media_message(payload, "video"), 1
        if service_type in (33, 37):
            detail = fields_map(payload)
            is_large = service_type == 37
            segment = {
                "type": "face",
                "data": {
                    "face_id": str(get_varint(detail, 3 if is_large else 1)),
                    "is_large": is_large,
                },
            }
            consumed = 1
            if is_large and index + 1 < len(elems) and 1 in fields_map(elems[index + 1]):
                consumed = 2
            return segment, consumed
        if service_type == 45 and business_type == 1:
            markdown = fields_map(payload)
            return {
                "type": "markdown",
                "data": {"content": _string(markdown, 1)},
            }, 1

    if 5 in elem:
        trans = fields_map(get_bytes(elem, 5))
        if get_varint(trans, 1) == 24:
            return _parse_group_file(get_bytes(trans, 2)), 1

    if 6 in elem:
        market = fields_map(get_bytes(elem, 6))
        face_id = get_bytes(market, 4).hex()
        market_segment: dict[str, Any] = {
            "type": "market_face",
            "data": {
                "emoji_package_id": get_varint(market, 5),
                "emoji_id": face_id,
                "key": _string(market, 7),
                "summary": _string(market, 1),
                "url": (
                    "https://gxh.vip.qq.com/club/item/parcel/item/"
                    f"{face_id[:2]}/{face_id}/raw300.gif"
                )
                if face_id
                else "",
            },
        }
        consumed = 1
        if index + 1 < len(elems):
            next_text = fields_map(elems[index + 1])
            if (
                1 in next_text
                and _string(fields_map(get_bytes(next_text, 1)), 1)
                == market_segment["data"]["summary"]
            ):
                consumed = 2
        return market_segment, consumed

    if 12 in elem:
        rich_msg = fields_map(get_bytes(elem, 12))
        forward_segment = _parse_forward_xml(get_bytes(rich_msg, 1))
        if forward_segment is not None:
            return forward_segment, 1

    if 51 in elem:
        light_app = fields_map(get_bytes(elem, 51))
        data = _inflate_prefixed(get_bytes(light_app, 1))
        if data is None:
            return None, 1
        try:
            light_payload: Any = json.loads(data)
        except json.JSONDecodeError:
            return {
                "type": "light_app",
                "data": {"app_name": "", "json_payload": data.decode(errors="replace")},
            }, 1
        app = str(light_payload.get("app", "")) if isinstance(light_payload, dict) else ""
        if app == "com.tencent.multimsg" and isinstance(light_payload, dict):
            forward_meta = light_payload.get("meta")
            forward_detail = forward_meta.get("detail") if isinstance(forward_meta, dict) else None
            if isinstance(forward_detail, dict):
                news = forward_detail.get("news")
                preview = []
                if isinstance(news, list):
                    preview = [str(item.get("text", "")) for item in news if isinstance(item, dict)]
                return {
                    "type": "forward",
                    "data": {
                        "forward_id": str(forward_detail.get("resid", "")),
                        "title": str(forward_detail.get("source", "")),
                        "preview": preview,
                        "summary": str(forward_detail.get("summary", "")),
                    },
                }, 1
        return {
            "type": "light_app",
            "data": {"app_name": app, "json_payload": data.decode(errors="replace")},
        }, 1

    return None, 1


def _parse_reply(src: dict[int, list[Any]], *, scene: str) -> dict[str, Any]:
    reserve = fields_map(get_bytes(src, 8)) if get_bytes(src, 8) else {}
    packed_sequences = get_bytes(src, 1)
    sequences: list[int] = []
    from .binary import BinaryReader
    from .protobuf import decode_varint

    if packed_sequences:
        reader = BinaryReader(packed_sequences)
        while reader.remaining:
            sequences.append(decode_varint(reader))
    sequence = sequences[0] if scene == "group" and sequences else get_varint(reserve, 8)
    sender_name = ""
    source_raw = get_bytes(src, 9)
    if source_raw:
        source = fields_map(source_raw)
        routing = fields_map(get_bytes(source, 1))
        group = fields_map(get_bytes(routing, 8))
        c2c = fields_map(get_bytes(routing, 7))
        sender_name = _string(group, 4) or _string(c2c, 6)
    reply_segments: list[dict[str, Any]] = []
    elems = [element.value for element in src.get(5, []) if isinstance(element.value, bytes)]
    index = 0
    while index < len(elems):
        segment, consumed = parse_elem(elems, index, scene=scene)
        index += consumed
        if segment is not None:
            reply_segments.append(segment)
    return {
        "type": "reply",
        "data": {
            "message_seq": sequence,
            "sender_id": get_varint(src, 2),
            "sender_name": sender_name or None,
            "time": get_varint(src, 3),
            "segments": reply_segments,
        },
    }


def _parse_media_message(payload: bytes, segment_type: str) -> dict[str, Any]:
    msg_info = fields_map(payload)
    body_items = msg_info.get(1, [])
    body = (
        fields_map(body_items[0].value)
        if body_items and isinstance(body_items[0].value, bytes)
        else {}
    )
    index = fields_map(get_bytes(body, 1))
    info = fields_map(get_bytes(index, 1))
    ext = fields_map(get_bytes(msg_info, 2))
    data: dict[str, Any] = {
        "resource_id": _string(index, 2),
        "temp_url": "",
    }
    if segment_type == "image":
        pic = fields_map(get_bytes(ext, 1))
        data.update(
            {
                "width": get_varint(info, 6),
                "height": get_varint(info, 7),
                "summary": _string(pic, 2) or "[图片]",
                "sub_type": "normal" if get_varint(pic, 1) == 0 else "sticker",
            }
        )
    elif segment_type == "record":
        data["duration"] = get_varint(info, 8)
    else:
        data.update(
            {
                "duration": get_varint(info, 8),
                "width": get_varint(info, 6),
                "height": get_varint(info, 7),
            }
        )
    return {"type": segment_type, "data": data}


def _parse_group_file(payload: bytes) -> dict[str, Any] | None:
    if len(payload) < 3:
        return None
    length = int.from_bytes(payload[1:3], "big")
    extra = fields_map(payload[3 : 3 + length])
    inner = fields_map(get_bytes(extra, 7))
    info = fields_map(get_bytes(inner, 2))
    file_id = _string(info, 2)
    if not file_id:
        return None
    return {
        "type": "file",
        "data": {
            "file_id": file_id,
            "file_name": _string(info, 4),
            "file_size": get_varint(info, 3),
            "file_hash": _string(info, 8) or None,
        },
    }


def _parse_forward_xml(payload: bytes) -> dict[str, Any] | None:
    data = _inflate_prefixed(payload)
    if data is None:
        return None
    text = data.decode("utf-8", errors="replace")
    res_id = _xml_first(text, r'resid="([^"]+)"')
    if not res_id:
        return None
    titles = re.findall(r'<title[^>]*text="([^"]*)"', text)
    summaries = re.findall(r'<summary[^>]*text="([^"]*)"', text)
    return {
        "type": "forward",
        "data": {
            "forward_id": res_id,
            "title": _xml_unescape(titles[0]) if titles else "",
            "preview": [_xml_unescape(value) for value in titles[1:]],
            "summary": _xml_unescape(summaries[0]) if summaries else "",
        },
    }


def _xml_first(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return _xml_unescape(match.group(1)) if match else ""


def _xml_unescape(value: str) -> str:
    return (
        value.replace("&#44;", ",")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _inflate_prefixed(payload: bytes) -> bytes | None:
    if len(payload) <= 1:
        return None
    try:
        return zlib.decompress(payload[1:])
    except zlib.error:
        pass
    try:
        return gzip.decompress(payload[1:])
    except OSError:
        pass
    try:
        return zlib.decompress(payload)
    except zlib.error:
        return None


async def build_outgoing_elems(
    bot: Bot,
    *,
    scene: str,
    peer_id: int,
    peer_uid: str,
    segments: list[dict[str, Any]],
) -> list[bytes]:
    elements: list[bytes] = []
    for segment in segments:
        segment_type = str(segment.get("type", ""))
        data = segment.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"{segment_type} 消息段缺少 data")
        if segment_type == "text":
            text = data.get("text")
            if not isinstance(text, str):
                raise ValueError("text 消息段缺少 data.text")
            elements.append(_text_elem(text))
        elif segment_type == "mention":
            user_id = int(data.get("user_id", 0))
            uid = await bot.get_uid_by_uin(user_id, group_id=peer_id, scene=scene)
            name = await bot.get_display_name(user_id, group_id=peer_id, scene=scene)
            reserve = field_varint(3, 2) + field_varint(4, user_id) + field_string(9, uid)
            elements.append(_text_elem(f"@{name}", reserve))
        elif segment_type == "mention_all":
            elements.append(_text_elem("@全体成员", field_varint(3, 1)))
        elif segment_type == "face":
            face_id = int(data.get("face_id", 0))
            if bool(data.get("is_large", False)):
                detail = bot._face_details.get(str(face_id))
                if detail is None:
                    raise ValueError(f"未知超级表情 {face_id}")
                payload = (
                    field_string(1, str(detail.get("aniStickerPackId", "")))
                    + field_string(2, str(detail.get("aniStickerId", "")))
                    + field_varint(3, face_id)
                    + field_varint(4, 1)
                    + field_varint(5, int(detail.get("aniStickerType", 0)))
                    + field_string(7, str(detail.get("qDes", "")))
                    + field_varint(9, 1)
                )
                common = (
                    field_varint(1, 37)
                    + field_bytes(2, payload)
                    + field_varint(3, int(detail.get("aniStickerType", 0)))
                )
            else:
                common = None
            if common is not None:
                elements.append(field_message(53, common))
            else:
                elements.append(field_message(2, field_varint(1, face_id)))
        elif segment_type == "reply":
            sequence = int(data.get("message_seq", 0))
            history = await bot.get_history_messages(
                scene=scene,
                peer_id=peer_id,
                limit=1,
                start_sequence=sequence,
            )
            target = next(
                (item for item in history.messages if item.sequence == sequence),
                history.messages[0] if history.messages else None,
            )
            if target is None:
                raise ValueError(f"无法引用消息 {sequence}: 消息不存在")
            source_common = fields_map(target.raw)
            target_body = fields_map(_entry(source_common, 3))
            target_rich = fields_map(_entry(target_body, 1))
            source_elems = [
                item.value for item in target_rich.get(2, []) if isinstance(item.value, bytes)
            ]
            reserve = (
                field_varint(1, 2)
                + field_varint(2, target.random)
                + field_string(3, target.sender_uid)
            )
            src_msg = (
                field_bytes(1, _packed_varints([sequence]))
                + field_varint(2, target.sender_id)
                + field_varint(3, target.timestamp)
                + field_varint(4, 0)
                + b"".join(field_message(5, item) for item in source_elems)
                + field_bytes(8, reserve)
            )
            elements.append(field_message(45, src_msg))
            if scene == "group":
                uid = target.sender_uid
                mention_reserve = (
                    field_varint(3, 2) + field_varint(4, target.sender_id) + field_string(9, uid)
                )
                elements.append(_text_elem(f"@{target.sender_id}", mention_reserve))
                elements.append(_text_elem(" "))
        elif segment_type == "light_app":
            json_payload = data.get("json_payload")
            if not isinstance(json_payload, str):
                raise ValueError("light_app 消息段缺少 data.json_payload")
            compressed = bytes([1]) + zlib.compress(json_payload.encode())
            elements.append(field_message(51, field_bytes(1, compressed)))
        elif segment_type == "image":
            raise ValueError("图片发送需要 Highway 上传，当前协议核心未完成该链路")
        elif segment_type == "record":
            raise ValueError("语音发送需要 SILK/Highway，当前协议环境未安装媒体编码器")
        elif segment_type == "video":
            raise ValueError("视频发送需要 Highway，当前协议核心未完成该链路")
        elif segment_type == "forward":
            raise ValueError("合并转发发送尚未接入长消息服务")
        else:
            raise ValueError(f"不支持的发送消息段类型: {segment_type}")
    return elements


def _text_elem(text: str, reserve: bytes = b"") -> bytes:
    value = field_string(1, text)
    if reserve:
        value += field_bytes(12, reserve)
    return field_message(1, value)


def _packed_varints(values: list[int]) -> bytes:
    from .protobuf import encode_varint

    return b"".join(encode_varint(value) for value in values)


def build_send_message(
    *,
    scene: str,
    peer_id: int,
    peer_uid: str,
    elems: list[bytes],
    client_sequence: int,
    random: int,
) -> bytes:
    if scene == "friend":
        routing = field_message(
            1,
            field_varint(1, peer_id)
            + field_string(2, peer_uid)
            + field_varint(3, 0)
            + field_varint(4, 0),
        )
    else:
        routing = field_message(
            2,
            field_varint(1, peer_id),
        )
    content_head = field_varint(1, 1)
    rich = b"".join(field_message(2, element) for element in elems)
    body = field_message(1, rich)
    return (
        field_message(1, routing)
        + field_message(2, content_head)
        + field_message(3, body)
        + field_varint(4, client_sequence)
        + field_varint(5, random)
    )


def parse_send_message_response(payload: bytes) -> tuple[int, str, int, int]:
    fields = fields_map(payload)
    return (
        get_varint(fields, 1),
        _string(fields, 2),
        get_varint(fields, 3),
        get_varint(fields, 11),
    )


def build_friend_history_request(peer_uid: str, start_sequence: int, end_sequence: int) -> bytes:
    return (
        field_string(2, peer_uid) + field_varint(3, start_sequence) + field_varint(4, end_sequence)
    )


def parse_friend_history_response(payload: bytes) -> list[bytes]:
    fields = fields_map(payload)
    retcode = get_varint(fields, 1)
    if retcode != 0:
        raise ValueError(_string(fields, 2) or f"SsoGetC2cMsg 返回 {retcode}")
    return [item.value for item in fields.get(7, []) if isinstance(item.value, bytes)]


def build_group_history_request(group_id: int, start_sequence: int, end_sequence: int) -> bytes:
    group_info = (
        field_varint(1, group_id) + field_varint(2, start_sequence) + field_varint(3, end_sequence)
    )
    return field_message(1, group_info) + field_varint(2, 1)


def parse_group_history_response(payload: bytes) -> list[bytes]:
    fields = fields_map(payload)
    retcode = get_varint(fields, 1)
    if retcode != 0:
        raise ValueError(_string(fields, 2) or f"SsoGetGroupMsg 返回 {retcode}")
    body = fields_map(get_bytes(fields, 3))
    inner_retcode = get_varint(body, 1)
    if inner_retcode != 0:
        raise ValueError(_string(body, 2) or f"SsoGetGroupMsg body 返回 {inner_retcode}")
    return [item.value for item in body.get(6, []) if isinstance(item.value, bytes)]


def build_peer_sequence_request(peer_uid: str) -> bytes:
    return field_string(1, peer_uid)


def parse_peer_sequence_response(payload: bytes) -> int:
    fields = fields_map(payload)
    return max(get_varint(fields, 3), get_varint(fields, 4))


def build_recall_friend(
    *,
    target_uid: str,
    client_sequence: int,
    message_sequence: int,
    random: int,
    timestamp: int,
) -> bytes:
    info = (
        field_varint(1, client_sequence)
        + field_varint(2, random)
        + field_varint(3, (0x01000000 << 32) | random)
        + field_varint(4, timestamp)
        + field_varint(5, 0)
        + field_varint(6, message_sequence)
    )
    settings = field_varint(1, 0) + field_varint(2, 0)
    return (
        field_varint(1, 1)
        + field_string(3, target_uid)
        + field_message(4, info)
        + field_message(5, settings)
        + field_varint(6, 0)
    )


def build_recall_group(group_id: int, sequence: int) -> bytes:
    return (
        field_varint(1, 1)
        + field_varint(2, group_id)
        + field_message(3, field_varint(1, sequence) + field_varint(3, 0))
        + field_message(4, field_varint(1, 0))
    )


def build_read_report(
    *,
    group_id: int | None,
    target_uid: str | None,
    sequence: int,
    timestamp: int,
) -> bytes:
    if target_uid is not None:
        c2c = field_string(2, target_uid) + field_varint(3, timestamp) + field_varint(4, sequence)
        return field_message(2, c2c)
    group = field_varint(1, group_id or 0) + field_varint(2, sequence)
    return field_message(1, group)


def build_receive_long_message(res_id: str, *, uid: str, os_name: str) -> bytes:
    client_type = 1 if os_name in {"Windows", "Linux", "Mac"} else 2
    platform = {"Windows": 3, "Linux": 6, "Mac": 7}.get(os_name, 9)
    recv = field_message(1, field_string(2, uid)) + field_string(2, res_id) + field_varint(3, 3)
    attr = (
        field_varint(1, 2)
        + field_varint(2, client_type)
        + field_varint(3, platform)
        + field_varint(4, 0)
    )
    return field_message(1, recv) + field_message(15, attr)


def parse_received_long_messages(payload: bytes) -> list[bytes]:
    response = fields_map(payload)
    recv = fields_map(get_bytes(response, 1))
    compressed = get_bytes(recv, 4)
    if not compressed:
        return []
    decompressed = gzip.decompress(compressed)
    transmit = fields_map(decompressed)
    for item in transmit.get(2, []):
        if not isinstance(item.value, bytes):
            continue
        entry = fields_map(item.value)
        if _string(entry, 1) == "MultiMsg":
            buffer = fields_map(get_bytes(entry, 2))
            return [value.value for value in buffer.get(1, []) if isinstance(value.value, bytes)]
    return []


def parse_forwarded_nodes(messages: list[bytes]) -> list[ForwardedNode]:
    nodes: list[ForwardedNode] = []
    for raw in messages:
        common = fields_map(raw)
        routing = fields_map(_entry(common, 1))
        content = fields_map(_entry(common, 2))
        body = fields_map(_entry(common, 3))
        rich = fields_map(_entry(body, 1))
        forward_ext = fields_map(get_bytes(content, 15))
        group = fields_map(get_bytes(routing, 8))
        c2c = fields_map(get_bytes(routing, 7))
        sender_name = _string(c2c, 6) or _string(group, 4)
        elems = [item.value for item in rich.get(2, []) if isinstance(item.value, bytes)]
        segments: list[dict[str, Any]] = []
        index = 0
        while index < len(elems):
            segment, consumed = parse_elem(elems, index, scene="friend")
            index += consumed
            if segment is not None:
                segments.append(segment)
        nodes.append(
            ForwardedNode(
                sequence=get_varint(content, 5),
                sender_name=sender_name,
                avatar_url=_string(forward_ext, 5),
                timestamp=get_varint(content, 6),
                segments=segments,
            )
        )
    return nodes


def timestamp_now() -> int:
    return int(time.time())


def data_uri_to_bytes(uri: str) -> bytes:
    if uri.startswith("base64://"):
        return base64.b64decode(uri[9:])
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    raise ValueError("仅支持解析 base64:// 或 data: URI")
