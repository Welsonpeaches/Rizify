from __future__ import annotations

from acidify_core.app_info import Bundled
from acidify_core.crypto import tea_decrypt
from acidify_core.protobuf import fields_map, get_bytes, get_varint
from acidify_core.session import SessionStore
from acidify_core.tlv import build_login_tlvs, build_qr_tlvs, parse_tlv


def _session() -> SessionStore:
    return SessionStore(
        uin=10001,
        guid=bytes(range(16)),
        device_name="流转者-00112233",
        encrypted_a1=b"A" * 32,
        tgtgt=b"T" * 16,
        no_pic_sig=b"P" * 16,
    )


def test_linux_53644_d1_uses_gen_info() -> None:
    tlvs = parse_tlv(build_qr_tlvs(Bundled.Linux_53644, _session()))
    d1 = fields_map(tlvs[0xD1])
    system = fields_map(get_bytes(d1, 1))
    gen_info = fields_map(get_bytes(d1, 4))
    assert get_bytes(system, 1) == b"Linux"
    assert get_bytes(system, 2) == "流转者-00112233".encode()
    assert get_varint(gen_info, 3) == 1600001615
    assert get_varint(gen_info, 6) == 1
    assert 2 not in d1


def test_legacy_linux_d1_keeps_type_buf() -> None:
    for app_info in (Bundled.Linux_39038, Bundled.Linux_46494):
        tlvs = parse_tlv(build_qr_tlvs(app_info, _session()))
        d1 = fields_map(tlvs[0xD1])
        assert get_bytes(d1, 4) == bytes.fromhex("3001")


def test_login_tlv_contains_required_106_and_144() -> None:
    tlvs = parse_tlv(build_login_tlvs(Bundled.Linux_53644, _session()))
    assert tlvs[0x106] == b"A" * 32
    inner = parse_tlv(tea_decrypt(tlvs[0x144], b"T" * 16))
    assert inner[0x16E] == "流转者-00112233".encode()


def test_tlv_builder_roundtrip() -> None:
    from acidify_core.tlv import TlvBuilder

    builder = TlvBuilder()
    builder.add(0x10, b"a" * 10)
    builder.add(0x11, b"b" * 8)
    parsed = parse_tlv(builder.build())
    assert parsed == {0x10: b"a" * 10, 0x11: b"b" * 8}
