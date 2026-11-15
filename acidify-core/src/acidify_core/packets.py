from __future__ import annotations

import contextlib
import secrets
import time
import zlib
from dataclasses import dataclass

from .app_info import AppInfo
from .binary import (
    BinaryReader,
    i32,
    prefixed_u16,
    prefixed_u32,
    u8,
    u16,
    u32,
    u64,
)
from .crypto import Secp192K1, tea_decrypt, tea_encrypt
from .exceptions import WtLoginError
from .protobuf import (
    field_bytes,
    field_message,
    field_string,
    field_varint,
    fields_map,
    get_bytes,
    get_varint,
)
from .session import SessionStore
from .tlv import build_login_tlvs, build_qr_tlvs, parse_tlv

WTLOGIN_BOB_PUBLIC = bytes.fromhex(
    "04928D8850673088B343264E0C6BACB8496D697799F37211DEB25BB73906CB089"
    "FEA9639B4E0260498B51A992D50813DA8"
)
SSO_FIXED_BYTES = bytes.fromhex("020000000000000000000000")


@dataclass(slots=True)
class SsoResponse:
    ret_code: int
    command: str
    payload: bytes
    sequence: int
    extra: str = ""


@dataclass(slots=True)
class QRCode:
    qr_sig: bytes
    url: str
    qr_string: str
    png: bytes


@dataclass(slots=True)
class QRCodeState:
    state: int
    uin: int = 0
    tgtgt: bytes = b""
    encrypted_a1: bytes = b""
    no_pic_sig: bytes = b""


@dataclass(slots=True)
class LoginTickets:
    d2_key: bytes
    uid: str
    a2: bytes
    d2: bytes
    encrypted_a1: bytes


def generate_trace() -> str:
    alphabet = "1234567890abcdef"
    return (
        "00-"
        + "".join(secrets.choice(alphabet) for _ in range(32))
        + "-"
        + "".join(secrets.choice(alphabet) for _ in range(16))
        + "-01"
    )


def build_reserved_fields(
    msg_type: int, uid: str, sign: bytes, token: bytes, extra: bytes
) -> bytes:
    output = field_string(15, generate_trace()) + field_string(16, uid)
    output += field_varint(21, msg_type)
    if sign or token or extra:
        secure_info = b""
        if sign:
            secure_info += field_bytes(1, sign)
        # Kotlin's protobuf encoder emits field 2 even when sec_token is empty.
        secure_info += field_bytes(2, token)
        if extra:
            secure_info += field_bytes(3, extra)
        output += field_message(24, secure_info)
    return output


def encode_sso_packet(
    *,
    app_info: AppInfo,
    session: SessionStore,
    command: str,
    sequence: int,
    payload: bytes,
    request_type: str,
    encrypt_type: str,
    msg_type: int,
    sign: bytes = b"",
    token: bytes = b"",
    extra: bytes = b"",
) -> bytes:
    reserved = build_reserved_fields(msg_type, session.uid, sign, token, extra)
    auth_flag = {"none": 0, "d2": 1, "empty": 2}[encrypt_type]
    key = session.d2_key if encrypt_type == "d2" else bytes(16)
    if request_type == "d2":
        sso_head = (
            i32(sequence)
            + i32(app_info.sub_app_id)
            + i32(2052)
            + SSO_FIXED_BYTES
            + prefixed_u32(session.a2, include_prefix=True)
            + prefixed_u32(command.encode(), include_prefix=True)
            + prefixed_u32(b"", include_prefix=True)
            + prefixed_u32(session.guid.hex().encode(), include_prefix=True)
            + prefixed_u32(b"", include_prefix=True)
            + prefixed_u16(app_info.current_version.encode(), include_prefix=True)
            + prefixed_u32(reserved, include_prefix=True)
        )
        inner = prefixed_u32(sso_head, include_prefix=True) + prefixed_u32(
            payload, include_prefix=True
        )
        body = (
            i32(12)
            + u8(auth_flag)
            + prefixed_u32(session.d2 if encrypt_type == "d2" else b"", include_prefix=True)
            + u8(0)
            + prefixed_u32(str(session.uin).encode(), include_prefix=True)
            + _encrypt_body(inner, encrypt_type, key)
        )
    else:
        sso_head = (
            prefixed_u32(command.encode(), include_prefix=True)
            + i32(4)
            + prefixed_u32(reserved, include_prefix=True)
        )
        inner = prefixed_u32(sso_head, include_prefix=True) + prefixed_u32(
            payload, include_prefix=True
        )
        body = (
            i32(13)
            + u8(auth_flag)
            + i32(sequence)
            + u8(0)
            + prefixed_u32(str(session.uin).encode(), include_prefix=True)
            + _encrypt_body(inner, encrypt_type, key)
        )
    return prefixed_u32(body, include_prefix=True)


def _encrypt_body(data: bytes, encrypt_type: str, key: bytes) -> bytes:
    if encrypt_type == "none":
        return data
    return tea_encrypt(data, key)


def decode_sso_packet(frame: bytes, d2_key: bytes) -> SsoResponse:
    try:
        return _decode_sso_packet(frame, d2_key)
    except ValueError as error:
        raise ValueError(str(error)) from error


def _decode_sso_packet(frame: bytes, d2_key: bytes) -> SsoResponse:
    reader = BinaryReader(frame)
    protocol = reader.u32()
    auth_flag = reader.u8()
    if protocol not in (12, 13):
        raise ValueError(f"无法识别的 SSO 协议: {protocol}")
    reader.u8()
    reader.prefixed_u32_with_prefix()
    encrypted = reader.rest()
    if auth_flag == 0:
        decrypted = encrypted
    elif auth_flag == 1:
        try:
            decrypted = tea_decrypt(encrypted, d2_key)
        except ValueError as error:
            raise ValueError(
                f"{error}; encrypted_length={len(encrypted)}; "
                f"frame_length={len(frame)}; offset={reader.offset}"
            ) from error
    elif auth_flag == 2:
        decrypted = tea_decrypt(encrypted, bytes(16))
    else:
        raise ValueError(f"无法识别的 SSO 加密标志: {auth_flag}")
    inner = BinaryReader(decrypted)
    try:
        head_length = inner.u32()
        if head_length < 16 or head_length > len(decrypted):
            raise ValueError(f"无效的 SSO 头长度: {head_length}")
        head_end = head_length
        sequence = inner.u32()
        ret_code = inner.i32()
        extra = inner.prefixed_u32_with_prefix().decode(errors="replace")
        command = inner.prefixed_u32_with_prefix().decode(errors="replace")
        inner.offset = head_end
        payload = inner.prefixed_u32_with_prefix()
    except ValueError as error:
        raise ValueError(str(error)) from error
    if payload[:1] == b"x":
        with contextlib.suppress(zlib.error):
            payload = zlib.decompress(payload)
    return SsoResponse(ret_code, command, payload, sequence, extra)


class WtLoginCodec:
    def __init__(self) -> None:
        self.ecdh = Secp192K1()
        self.share_key = self.ecdh.key_exchange(WTLOGIN_BOB_PUBLIC, True)

    def wrap(
        self,
        app_info: AppInfo,
        uin: int,
        wt_login_sub_cmd: int,
        payload: bytes,
    ) -> bytes:
        encrypted = tea_encrypt(payload, self.share_key)
        body = (
            u16(8001)
            + u16(wt_login_sub_cmd)
            + u16(0)
            + u32(uin)
            + u8(3)
            + u8(135)
            + i32(0)
            + u8(19)
            + u16(0)
            + u16(app_info.app_client_version)
            + i32(0)
            + u8(1)
            + u8(1)
            + secrets.token_bytes(16)
            + u16(0x102)
            + prefixed_u16(self.ecdh.pack_public(compressed=True))
            + encrypted
            + u8(3)
        )
        return u8(2) + u16(len(body) + 3) + body

    def unwrap(self, payload: bytes) -> bytes:
        reader = BinaryReader(payload)
        if reader.u8() != 2:
            raise ValueError("无效的 wtlogin 响应头")
        reader.skip(15)
        encrypted = reader.read(reader.remaining - 1)
        decrypted = tea_decrypt(encrypted, self.share_key)
        if reader.u8() != 3:
            raise ValueError("wtlogin 响应结束标记无效")
        return decrypted


def build_fetch_qr_payload(
    app_info: AppInfo,
    session: SessionStore,
    unusual_sig: bytes | None = None,
) -> bytes:
    qr_tlv = build_qr_tlvs(app_info, session, unusual_sig)
    code2d = u16(0) + u32(app_info.app_id) + u64(0) + b"" + u8(0) + prefixed_u16(b"") + qr_tlv
    request_body = (
        i32(int(time.time()))
        + u8(0x2)
        + u16(43 + len(code2d) + 1)
        + u16(0x31)
        + bytes(21)
        + u8(0x3)
        + u16(0)
        + u16(0x32)
        + i32(0)
        + u64(0)
        + code2d
        + u8(0x3)
    )
    return (
        u8(0)
        + u16(len(request_body))
        + i32(app_info.app_id)
        + i32(0x72)
        + prefixed_u16(b"")
        + u8(0)
        + request_body
    )


def parse_fetch_qr_payload(payload: bytes) -> QRCode:
    reader = BinaryReader(payload)
    reader.u32()
    reader.skip(4)
    reader.u16()
    reader.skip(40)
    reader.u32()
    code2d = BinaryReader(reader.rest())
    code2d.u8()
    sig = code2d.prefixed_u16()
    tlvs = parse_tlv(code2d.rest())
    d1 = fields_map(tlvs[0xD1])
    url = get_bytes(d1, 2).decode(errors="replace")
    qr_string = get_bytes(d1, 3).decode(errors="replace")
    return QRCode(sig, url, qr_string, tlvs[0x17])


def build_query_qr_payload(app_info: AppInfo, session: SessionStore) -> bytes:
    request_body = (
        u16(0)
        + u32(app_info.app_id)
        + prefixed_u16(session.qr_sig)
        + u64(0)
        + u8(0)
        + prefixed_u16(b"")
        + u16(0)
    )
    return (
        u8(0)
        + u16(len(request_body))
        + i32(app_info.app_id)
        + i32(0x72)
        + prefixed_u16(b"")
        + u8(0)
        + request_body
    )


def parse_query_qr_payload(payload: bytes) -> QRCodeState:
    reader = BinaryReader(payload)
    reader.u32()
    reader.skip(4)
    reader.u16()
    reader.skip(40)
    reader.u32()
    code2d = BinaryReader(reader.rest())
    state = code2d.u8()
    if state != 0:
        return QRCodeState(state)
    code2d.skip(4)
    uin = code2d.u32()
    code2d.skip(4)
    tlvs = parse_tlv(code2d.rest())
    return QRCodeState(
        state=state,
        uin=uin,
        tgtgt=tlvs[0x1E],
        encrypted_a1=tlvs[0x18],
        no_pic_sig=tlvs[0x19],
    )


def build_pc_login_payload(app_info: AppInfo, session: SessionStore) -> bytes:
    return u16(9) + build_login_tlvs(app_info, session)


def parse_pc_login_payload(payload: bytes, tgtgt: bytes) -> LoginTickets:
    reader = BinaryReader(payload)
    reader.u16()
    state = reader.u8()
    tlvs = parse_tlv(reader.rest())
    if state != 0:
        if 0x146 in tlvs:
            detail = BinaryReader(tlvs[0x146])
            code = detail.i32()
            tag = detail.prefixed_u16().decode(errors="replace")
            message = detail.prefixed_u16().decode(errors="replace")
            raise WtLoginError(code, tag, message)
        raise WtLoginError(state, "", "登录票据交换失败")
    internal = parse_tlv(tea_decrypt(tlvs[0x119], tgtgt))
    uid_543 = fields_map(internal[0x543])
    layer1 = fields_map(get_bytes(uid_543, 9))
    layer2 = fields_map(get_bytes(layer1, 11))
    return LoginTickets(
        d2_key=internal[0x305],
        uid=get_bytes(layer2, 1).decode(errors="replace"),
        a2=internal[0x10A],
        d2=internal[0x143],
        encrypted_a1=internal[0x106],
    )


def build_bot_online_payload(app_info: AppInfo, session: SessionStore) -> bytes:
    os_version = {
        "Windows": "Windows 10.0.19042",
        "Mac": "macOS 14.4.1",
        "Linux": "Ubuntu 22.04.4 LTS",
    }.get(app_info.os, "")
    business = field_varint(1, 1) + field_varint(2, 1)
    device = (
        field_string(1, session.device_name)
        + field_string(2, app_info.kernel)
        + field_string(3, os_version)
        + field_string(5, app_info.vendor_os)
    )
    return (
        field_string(1, session.guid.hex())
        + field_string(3, app_info.current_version)
        + field_message(6, device)
        + field_message(10, business)
    )


def parse_register_response(payload: bytes) -> str:
    return get_bytes(fields_map(payload), 2).decode(errors="replace")


def build_alive_payload() -> bytes:
    return bytes.fromhex("00000004")


def build_text_element(text: str) -> bytes:
    text_proto = field_string(1, text)
    return field_message(1, text_proto)


def build_send_private_text(
    friend_uin: int,
    friend_uid: str,
    text: str,
    client_sequence: int,
    random: int,
) -> bytes:
    routing = field_message(1, field_varint(1, friend_uin) + field_string(2, friend_uid))
    content_head = field_varint(1, 1)
    rich_text = field_message(2, build_text_element(text))
    body = field_message(1, rich_text)
    return (
        field_message(1, routing)
        + field_message(2, content_head)
        + field_message(3, body)
        + field_varint(4, client_sequence)
        + field_varint(5, random)
    )


def build_send_group_text(
    group_uin: int,
    text: str,
    client_sequence: int,
    random: int,
) -> bytes:
    routing = field_message(2, field_varint(1, group_uin))
    content_head = field_varint(1, 1)
    rich_text = field_message(2, build_text_element(text))
    body = field_message(1, rich_text)
    return (
        field_message(1, routing)
        + field_message(2, content_head)
        + field_message(3, body)
        + field_varint(4, client_sequence)
        + field_varint(5, random)
    )


@dataclass(slots=True)
class SendMessageResult:
    result: int
    error_message: str
    send_time: int
    sequence: int


def parse_send_message_response(payload: bytes) -> SendMessageResult:
    fields = fields_map(payload)
    result = get_varint(fields, 1)
    error_message = get_bytes(fields, 2).decode(errors="replace")
    if result != 0:
        from .exceptions import MessageSendError

        raise MessageSendError(result, error_message)
    return SendMessageResult(
        result=result,
        error_message=error_message,
        send_time=get_varint(fields, 3),
        sequence=get_varint(fields, 11) or get_varint(fields, 14),
    )
