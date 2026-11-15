from __future__ import annotations

import os

import pytest
from acidify_core.crypto import (
    SECP192K1,
    Secp192K1,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    tea_decrypt,
    tea_encrypt,
)


@pytest.mark.parametrize("length", [0, 1, 2, 7, 8, 9, 15, 16, 17, 63, 255, 499])
def test_tea_roundtrip_all_padding_paths(length: int) -> None:
    key = b"0123456789abcdef"
    plain = os.urandom(length)
    cipher = tea_encrypt(plain, key)
    assert len(cipher) % 8 == 0
    assert tea_decrypt(cipher, key) == plain


def test_tea_rejects_invalid_key_or_ciphertext() -> None:
    with pytest.raises(ValueError):
        tea_encrypt(b"x", b"short")
    with pytest.raises(ValueError):
        tea_decrypt(b"short", b"0123456789abcdef")


def test_aes_gcm_nist_vector() -> None:
    key = bytes.fromhex("00000000000000000000000000000000")
    iv = bytes.fromhex("000000000000000000000000")
    plaintext = bytes.fromhex("00000000000000000000000000000000")
    expected = bytes.fromhex("0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf")
    ciphertext = aes_gcm_encrypt(key, iv, plaintext)
    assert ciphertext == expected
    assert aes_gcm_decrypt(key, iv, ciphertext) == plaintext


def test_secp192k1_shared_secret_is_symmetric() -> None:
    alice = Secp192K1(bytes.fromhex("01"))
    bob = Secp192K1(bytes.fromhex("02"))
    alice_secret = alice.key_exchange(bob.pack_public())
    bob_secret = bob.key_exchange(alice.pack_public())
    assert alice_secret == bob_secret
    assert len(alice_secret) == SECP192K1.size
    assert bob.key_exchange(alice.pack_public(compressed=True)) == bob_secret


def test_secp192k1_known_public_key() -> None:
    key = Secp192K1(bytes.fromhex("01"))
    assert key.pack_public().hex() == (
        "04"
        "db4ff10ec057e9ae26b07d0280b7f4341da5d1b1eae06c7d"
        "9b2f2f6d9c5628a7844163d015be86344082aa88d95e2f9d"
    )
