from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .binary import BinaryReader

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH = 2
WIRE_32BIT = 5


def encode_varint(value: int) -> bytes:
    if value < 0:
        value &= 0xFFFFFFFFFFFFFFFF
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def decode_varint(reader: BinaryReader) -> int:
    shift = 0
    value = 0
    while True:
        byte = reader.u8()
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value
        shift += 7
        if shift > 70:
            raise ValueError("protobuf varint 过长")


def key(field_number: int, wire_type: int) -> bytes:
    if field_number <= 0:
        raise ValueError("protobuf 字段编号必须大于 0")
    return encode_varint((field_number << 3) | wire_type)


def field_varint(field_number: int, value: int) -> bytes:
    return key(field_number, WIRE_VARINT) + encode_varint(value)


def field_bytes(field_number: int, value: bytes) -> bytes:
    return key(field_number, WIRE_LENGTH) + encode_varint(len(value)) + value


def field_string(field_number: int, value: str) -> bytes:
    return field_bytes(field_number, value.encode("utf-8"))


def field_message(field_number: int, value: bytes) -> bytes:
    return field_bytes(field_number, value)


def field_fixed32(field_number: int, value: int) -> bytes:
    import struct

    return key(field_number, WIRE_32BIT) + struct.pack("<I", value & 0xFFFFFFFF)


def field_fixed64(field_number: int, value: int) -> bytes:
    import struct

    return key(field_number, WIRE_64BIT) + struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def field_packed_varints(field_number: int, values: Iterable[int]) -> bytes:
    packed = b"".join(encode_varint(value) for value in values)
    return field_bytes(field_number, packed)


@dataclass(slots=True)
class ProtoField:
    number: int
    wire_type: int
    value: int | bytes


def decode_fields(data: bytes) -> list[ProtoField]:
    import struct

    reader = BinaryReader(data)
    fields: list[ProtoField] = []
    while reader.remaining:
        tag = decode_varint(reader)
        number = tag >> 3
        wire_type = tag & 7
        if wire_type == WIRE_VARINT:
            value: int | bytes = decode_varint(reader)
        elif wire_type == WIRE_LENGTH:
            value = reader.read(decode_varint(reader))
        elif wire_type == WIRE_64BIT:
            value = struct.unpack("<Q", reader.read(8))[0]
        elif wire_type == WIRE_32BIT:
            value = struct.unpack("<I", reader.read(4))[0]
        else:
            raise ValueError(f"不支持的 protobuf wire type: {wire_type}")
        fields.append(ProtoField(number, wire_type, value))
    return fields


def fields_map(data: bytes) -> dict[int, list[ProtoField]]:
    result: dict[int, list[ProtoField]] = {}
    for field in decode_fields(data):
        result.setdefault(field.number, []).append(field)
    return result


def get_bytes(fields: dict[int, list[ProtoField]], number: int, default: bytes = b"") -> bytes:
    values = fields.get(number)
    if not values:
        return default
    value = values[-1].value
    if not isinstance(value, bytes):
        raise ValueError(f"protobuf 字段 {number} 不是 bytes")
    return value


def get_varint(fields: dict[int, list[ProtoField]], number: int, default: int = 0) -> int:
    values = fields.get(number)
    if not values:
        return default
    value = values[-1].value
    if not isinstance(value, int):
        raise ValueError(f"protobuf 字段 {number} 不是 varint")
    return value
