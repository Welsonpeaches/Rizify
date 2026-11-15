from __future__ import annotations

import struct
from typing import cast


def u8(value: int) -> bytes:
    return struct.pack(">B", value & 0xFF)


def u16(value: int) -> bytes:
    return struct.pack(">H", value & 0xFFFF)


def i16(value: int) -> bytes:
    return struct.pack(">h", value)


def u32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


def i32(value: int) -> bytes:
    return struct.pack(">i", value)


def u64(value: int) -> bytes:
    return struct.pack(">Q", value & 0xFFFFFFFFFFFFFFFF)


def i64(value: int) -> bytes:
    return struct.pack(">q", value)


def prefixed_u8(data: bytes, *, include_prefix: bool = False) -> bytes:
    if include_prefix:
        return u8(len(data) + 1) + data
    return u8(len(data)) + data


def prefixed_u16(data: bytes, *, include_prefix: bool = False) -> bytes:
    if include_prefix:
        return u16(len(data) + 2) + data
    return u16(len(data)) + data


def prefixed_u32(data: bytes, *, include_prefix: bool = False) -> bytes:
    if include_prefix:
        return u32(len(data) + 4) + data
    return u32(len(data)) + data


class BinaryReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read(self, length: int) -> bytes:
        if length < 0 or self.offset + length > len(self.data):
            raise ValueError("数据包长度不足")
        value = self.data[self.offset : self.offset + length]
        self.offset += length
        return value

    def skip(self, length: int) -> None:
        self.read(length)

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return cast(int, struct.unpack(">H", self.read(2))[0])

    def i16(self) -> int:
        return cast(int, struct.unpack(">h", self.read(2))[0])

    def u32(self) -> int:
        return cast(int, struct.unpack(">I", self.read(4))[0])

    def i32(self) -> int:
        return cast(int, struct.unpack(">i", self.read(4))[0])

    def u64(self) -> int:
        return cast(int, struct.unpack(">Q", self.read(8))[0])

    def i64(self) -> int:
        return cast(int, struct.unpack(">q", self.read(8))[0])

    def rest(self) -> bytes:
        return self.read(self.remaining)

    def prefixed_u8(self) -> bytes:
        return self.read(self.u8())

    def prefixed_u8_with_prefix(self) -> bytes:
        return self.read(self.u8() - 1)

    def prefixed_u16(self) -> bytes:
        return self.read(self.u16())

    def prefixed_u32(self) -> bytes:
        return self.read(self.u32())

    def prefixed_u32_with_prefix(self) -> bytes:
        return self.read(self.u32() - 4)
