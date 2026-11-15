from __future__ import annotations

from acidify_core.oidb import decode_oidb_envelope, encode_oidb_envelope
from acidify_core.protobuf import field_bytes, field_varint, fields_map


def test_oidb_envelope_uses_field_four_for_body() -> None:
    encoded = encode_oidb_envelope(0xFD4, 1, b"payload")
    fields = fields_map(encoded)
    assert fields[4][0].value == b"payload"
    assert 12 not in fields


def test_oidb_response_body_is_read_from_field_four() -> None:
    response = (
        field_varint(1, 0xFD4)
        + field_varint(2, 1)
        + field_varint(3, 0)
        + field_bytes(4, b"body")
        + field_bytes(5, b"")
    )
    assert decode_oidb_envelope(response) == b"body"
