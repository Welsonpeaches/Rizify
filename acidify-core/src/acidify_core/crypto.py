from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASK32 = 0xFFFFFFFF
TEA_DELTA = 0x9E3779B9


def md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def sha1(data: bytes) -> bytes:
    return hashlib.sha1(data).digest()


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def secure_random(length: int) -> bytes:
    return secrets.token_bytes(length)


def pbkdf2_sha256(password: str, salt: bytes, iterations: int = 120000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)


def _words(data: bytes) -> list[int]:
    if len(data) % 4:
        raise ValueError("TEA 输入长度必须是 4 的倍数")
    return list(struct.unpack(f">{len(data) // 4}I", data))


def _pack(words: list[int]) -> bytes:
    return struct.pack(f">{len(words)}I", *(word & MASK32 for word in words))


def _tea_encrypt_block(block: bytes, key: bytes) -> bytes:
    v0, v1 = _words(block)
    k0, k1, k2, k3 = _words(key)
    total = 0
    for _ in range(16):
        total = (total + TEA_DELTA) & MASK32
        v0 = (v0 + ((((v1 << 4) & MASK32) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))) & MASK32
        v1 = (v1 + ((((v0 << 4) & MASK32) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))) & MASK32
    return _pack([v0, v1])


def _tea_decrypt_block(block: bytes, key: bytes) -> bytes:
    v0, v1 = _words(block)
    k0, k1, k2, k3 = _words(key)
    total = (TEA_DELTA * 16) & MASK32
    for _ in range(16):
        v1 = (v1 - ((((v0 << 4) & MASK32) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))) & MASK32
        v0 = (v0 - ((((v1 << 4) & MASK32) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))) & MASK32
        total = (total - TEA_DELTA) & MASK32
    return _pack([v0, v1])


def tea_encrypt(data: bytes, key: bytes) -> bytes:
    if len(key) != 16:
        raise ValueError("TEA 密钥必须是 16 字节")
    padding = (8 - ((len(data) + 10) % 8)) % 8
    out_length = padding + len(data) + 10
    cipher = bytearray(out_length)
    pre_plain = bytearray(8)
    plain_buf = bytearray(8)
    header = True
    crypt = 0
    pre_crypt = 0
    pad2 = (len(data) + 10) % 8
    pos = (8 - pad2) if pad2 else 0
    plain_buf[0] = (secrets.randbelow(256) & 0xF8 | pos) & 0xFF
    for index in range(1, pos + 1):
        plain_buf[index] = secrets.randbelow(256)
    pos += 1
    pad = 1
    while pad <= 2:
        if pos < 8:
            plain_buf[pos] = secrets.randbelow(256)
            pos += 1
            pad += 1
        if pos == 8:
            pos, crypt, pre_crypt, header = _tea_encrypt_flush(
                plain_buf, cipher, pre_plain, crypt, pre_crypt, header, key
            )
    source_offset = 0
    remaining = len(data)
    while remaining > 0:
        if pos < 8:
            plain_buf[pos] = data[source_offset]
            pos += 1
            source_offset += 1
            remaining -= 1
        if pos == 8:
            pos, crypt, pre_crypt, header = _tea_encrypt_flush(
                plain_buf, cipher, pre_plain, crypt, pre_crypt, header, key
            )
    pad = 1
    while True:
        if pad <= 7:
            if pos < 8:
                plain_buf[pos] = 0
                pos += 1
                pad += 1
            if pos == 8:
                pos, crypt, pre_crypt, header = _tea_encrypt_flush(
                    plain_buf, cipher, pre_plain, crypt, pre_crypt, header, key
                )
        else:
            return bytes(cipher)


def _tea_encrypt_flush(
    plain: bytearray,
    cipher: bytearray,
    pre_plain: bytearray,
    crypt: int,
    pre_crypt: int,
    header: bool,
    key: bytes,
) -> tuple[int, int, int, bool]:
    block = bytearray(8)
    for index in range(8):
        if header:
            block[index] = plain[index] ^ pre_plain[index]
        else:
            block[index] = plain[index] ^ cipher[pre_crypt + index]
    encrypted = _tea_encrypt_block(bytes(block), key)
    cipher[crypt : crypt + 8] = encrypted
    for index in range(8):
        cipher[crypt + index] ^= pre_plain[index]
    pre_plain[:] = block
    return 0, crypt + 8, crypt, False


def tea_decrypt(data: bytes, key: bytes) -> bytes:
    if len(key) != 16:
        raise ValueError("TEA 密钥必须是 16 字节")
    if len(data) % 8 != 0 or len(data) < 16:
        raise ValueError("TEA 密文长度无效")
    pre_plain = bytearray(_tea_decrypt_block(data[:8], key))
    padding = pre_plain[0] & 7
    out_length = len(data) - padding - 10
    if out_length < 0:
        raise ValueError("TEA 解密长度无效")
    output = bytearray(out_length)
    pre_crypt = 0
    crypt = 8
    pos = padding + 1
    written = 0
    current = bytes(8)
    pad = 1
    while pad <= 2:
        if pos < 8:
            pos += 1
            pad += 1
        if pos == 8:
            _, pre_plain = _tea_decrypt_next(data, crypt, pre_plain, key)
            current = data
            crypt += 8
            pos = 0
    while written < out_length:
        if pos < 8:
            output[written] = current[pre_crypt + pos] ^ pre_plain[pos]
            written += 1
            pos += 1
        if pos == 8:
            if crypt + 8 > len(data):
                break
            pre_crypt = crypt - 8
            _, pre_plain = _tea_decrypt_next(data, crypt, pre_plain, key)
            current = data
            crypt += 8
            pos = 0
    pad = 1
    while pad < 8:
        if pos < 8:
            if current[pre_crypt + pos] ^ pre_plain[pos]:
                raise ValueError("TEA 填充校验失败")
            pos += 1
        if pos == 8:
            if crypt + 8 > len(data):
                break
            pre_crypt = crypt
            _, pre_plain = _tea_decrypt_next(data, crypt, pre_plain, key)
            current = data
            crypt += 8
            pos = 0
        pad += 1
    return bytes(output)


def _tea_decrypt_next(
    data: bytes, offset: int, pre_plain: bytearray, key: bytes
) -> tuple[bytes, bytearray]:
    if offset + 8 > len(data):
        return data, pre_plain
    block = bytearray(8)
    for index in range(8):
        block[index] = pre_plain[index] ^ data[offset + index]
    decrypted = bytearray(_tea_decrypt_block(bytes(block), key))
    return data, decrypted


def aes_gcm_encrypt(key: bytes, iv: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(key).encrypt(iv, plaintext, aad)


def aes_gcm_decrypt(key: bytes, iv: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(key).decrypt(iv, ciphertext, aad)


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


@dataclass(frozen=True, slots=True)
class Curve:
    p: int
    a: int
    b: int
    gx: int
    gy: int
    n: int
    size: int
    pack_size: int


SECP192K1 = Curve(
    p=int("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFEE37", 16),
    a=0,
    b=3,
    gx=int("DB4FF10EC057E9AE26B07D0280B7F4341DA5D1B1EAE06C7D", 16),
    gy=int("9B2F2F6D9C5628A7844163D015BE86344082AA88D95E2F9D", 16),
    n=int("FFFFFFFFFFFFFFFFFFFFFFFE26F2FC170F69466A74DEFD8D", 16),
    size=24,
    pack_size=24,
)


def _point_add(
    point1: tuple[int, int] | None,
    point2: tuple[int, int] | None,
    curve: Curve,
) -> tuple[int, int] | None:
    if point1 is None:
        return point2
    if point2 is None:
        return point1
    x1, y1 = point1
    x2, y2 = point2
    if x1 == x2:
        if (y1 + y2) % curve.p == 0:
            return None
        slope = ((3 * x1 * x1 + curve.a) * pow(2 * y1, -1, curve.p)) % curve.p
    else:
        slope = ((y2 - y1) * pow(x2 - x1, -1, curve.p)) % curve.p
    x3 = (slope * slope - x1 - x2) % curve.p
    y3 = (slope * (x1 - x3) - y1) % curve.p
    return x3, y3


def _point_mul(scalar: int, point: tuple[int, int] | None, curve: Curve) -> tuple[int, int] | None:
    result: tuple[int, int] | None = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend, curve)
        addend = _point_add(addend, addend, curve)
        scalar >>= 1
    return result


class Secp192K1:
    curve = SECP192K1

    def __init__(self, secret: bytes | None = None) -> None:
        self.secret = (
            int.from_bytes(secret, "big") if secret else secrets.randbelow(self.curve.n - 1) + 1
        )
        point = _point_mul(self.secret, (self.curve.gx, self.curve.gy), self.curve)
        if point is None:
            raise ValueError("生成的椭圆曲线公钥无效")
        self.public_point = point

    def pack_public(self, compressed: bool = False) -> bytes:
        x, y = self.public_point
        if compressed:
            prefix = 0x02 if y % 2 == 0 else 0x03
            return bytes([prefix]) + x.to_bytes(self.curve.size, "big")
        return b"\x04" + x.to_bytes(self.curve.size, "big") + y.to_bytes(self.curve.size, "big")

    def pack_secret(self) -> bytes:
        raw = self.secret.to_bytes((self.secret.bit_length() + 7) // 8, "big")
        return b"\x00\x00\x00" + bytes([len(raw)]) + raw

    def key_exchange(self, peer_public: bytes, hash_result: bool = False) -> bytes:
        if peer_public[0] == 0x04:
            if len(peer_public) != self.curve.size * 2 + 1:
                raise ValueError("EC public key length mismatch")
            x = int.from_bytes(peer_public[1 : 1 + self.curve.size], "big")
            y = int.from_bytes(peer_public[1 + self.curve.size :], "big")
        elif peer_public[0] in (0x02, 0x03):
            if len(peer_public) != self.curve.size + 1:
                raise ValueError("EC public key length mismatch")
            x = int.from_bytes(peer_public[1:], "big")
            value = (pow(x, 3, self.curve.p) + self.curve.a * x + self.curve.b) % self.curve.p
            y = pow(value, (self.curve.p + 1) // 4, self.curve.p)
            if y % 2 != (peer_public[0] & 1):
                y = self.curve.p - y
        else:
            raise ValueError("Unsupported EC public key format")
        shared = _point_mul(self.secret, (x, y), self.curve)
        if shared is None:
            raise ValueError("ECDH shared point is infinity")
        x_bytes = shared[0].to_bytes(self.curve.size, "big")
        if hash_result:
            return md5(x_bytes[: self.curve.pack_size])
        return x_bytes
