from __future__ import annotations

from collections import OrderedDict

from .app_info import AppInfo
from .binary import BinaryReader, i32, prefixed_u16, prefixed_u32, u8, u16, u32
from .crypto import tea_encrypt
from .protobuf import field_message, field_string, field_varint
from .session import SessionStore


class TlvBuilder:
    def __init__(self) -> None:
        self.entries: OrderedDict[int, bytes] = OrderedDict()

    def add(self, tag: int, value: bytes) -> None:
        self.entries[tag] = value

    def build(self) -> bytes:
        output = bytearray(u16(len(self.entries)))
        for tag, value in self.entries.items():
            output += u16(tag)
            output += u16(len(value))
            output += value
        return bytes(output)


def parse_tlv(data: bytes) -> dict[int, bytes]:
    reader = BinaryReader(data)
    count = reader.u16()
    result: dict[int, bytes] = {}
    for _ in range(count):
        tag = reader.u16()
        length = reader.u16()
        result[tag] = reader.read(length)
    return result


def build_qr_tlvs(
    app_info: AppInfo, session: SessionStore, unusual_sig: bytes | None = None
) -> bytes:
    builder = TlvBuilder()
    if unusual_sig is not None:
        builder.add(0x11, unusual_sig)
    builder.add(
        0x16,
        u32(0)
        + i32(app_info.app_id)
        + i32(app_info.sub_app_id)
        + session.guid
        + prefixed_u16(app_info.package_name.encode())
        + prefixed_u16(app_info.pt_version.encode())
        + prefixed_u16(app_info.package_name.encode()),
    )
    builder.add(
        0x1B,
        u32(0) + u32(0) + u32(3) + u32(4) + u32(72) + u32(2) + u32(2) + u16(0),
    )
    builder.add(
        0x1D,
        u8(1) + i32(app_info.main_sig_map) + u32(0) + u8(0),
    )
    builder.add(0x33, session.guid)
    builder.add(0x35, i32(app_info.sso_version))
    builder.add(0x66, i32(app_info.sso_version))
    system = field_string(1, app_info.os) + field_string(2, session.device_name)
    if app_info.app_client_version >= 53644:
        gen_info = field_varint(3, app_info.app_id) + field_varint(6, 1)
        d1 = field_message(1, system) + field_message(4, gen_info)
    else:
        d1 = field_message(1, system) + field_message(4, bytes.fromhex("3001"))
    builder.add(0xD1, d1)
    return builder.build()


def build_login_tlvs(app_info: AppInfo, session: SessionStore) -> bytes:
    inner = TlvBuilder()
    inner.add(0x16E, session.device_name.encode())
    inner.add(
        0x147,
        i32(app_info.app_id)
        + prefixed_u16(app_info.pt_version.encode())
        + prefixed_u16(app_info.package_name.encode()),
    )
    inner.add(
        0x128,
        u16(0)
        + u8(0)
        + u8(0)
        + u8(0)
        + u32(0)
        + prefixed_u16(app_info.os.encode())
        + prefixed_u16(session.guid)
        + prefixed_u16(b""),
    )
    inner.add(0x124, bytes(12))

    builder = TlvBuilder()
    builder.add(0x106, session.encrypted_a1)
    builder.add(0x144, tea_encrypt(inner.build(), session.tgtgt))
    builder.add(
        0x116,
        u8(0) + u32(12058620) + i32(app_info.sub_sig_map) + u8(0),
    )
    builder.add(
        0x142,
        u16(0) + prefixed_u16(app_info.package_name.encode()),
    )
    builder.add(0x145, session.guid)
    builder.add(
        0x18,
        u16(0) + u32(5) + u32(0) + u32(8001) + u32(session.uin) + u16(0) + u16(0),
    )
    builder.add(
        0x141,
        prefixed_u32(b"Unknown") + u32(0),
    )
    builder.add(
        0x177,
        u8(1) + u32(0) + prefixed_u16(app_info.wt_login_sdk.encode()),
    )
    builder.add(0x191, u8(0))
    builder.add(
        0x100,
        u16(0)
        + u32(5)
        + i32(app_info.app_id)
        + i32(app_info.sub_app_id)
        + i32(app_info.app_client_version)
        + i32(app_info.main_sig_map),
    )
    builder.add(
        0x107,
        u16(1) + u8(0x0D) + u16(0) + u8(1),
    )
    builder.add(0x318, b"")
    builder.add(0x16A, session.no_pic_sig)
    builder.add(0x166, u8(5))
    builder.add(0x521, u32(0x13) + prefixed_u16(b"basicim"))
    return builder.build()
