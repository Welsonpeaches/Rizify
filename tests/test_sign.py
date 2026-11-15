from __future__ import annotations

import json

import httpx
import pytest
from acidify_core.sign import LagrangeUrlSignProvider


@pytest.mark.asyncio
async def test_sign_request_method_path_and_payload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "value": {
                    "sec_sign": "aa",
                    "sec_token": "bb",
                    "sec_extra": "cc",
                },
            },
        )

    provider = LagrangeUrlSignProvider(
        "http://127.0.0.1:8080/",
        "token-value",
        10001,
        "00112233445566778899aabbccddeeff",
        "V1_LNX_NQ_3.2.34_53644_GW_B",
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await provider.sign("wtlogin.login", 42, b"\x01\x02")
    finally:
        await provider.close()
    assert result is not None
    assert result.sign == b"\xaa"
    assert result.token == b"\xbb"
    assert result.extra == b"\xcc"
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/sign/sec-sign"
    assert request.headers["Authorization"] == "Bearer token-value"
    body = json.loads(request.content)
    assert body == {
        "command": "wtlogin.login",
        "seq": 42,
        "body": "0102",
        "uin": 10001,
        "guid": "00112233445566778899aabbccddeeff",
        "qua": "V1_LNX_NQ_3.2.34_53644_GW_B",
    }


@pytest.mark.asyncio
async def test_command_outside_linux_whitelist_is_unsigned() -> None:
    provider = LagrangeUrlSignProvider(
        "http://127.0.0.1:8080/",
        "token",
        10001,
        "00" * 16,
        "V1_LNX_NQ_3.2.34_53644_GW_B",
    )
    try:
        assert await provider.sign("Unknown.Command", 1, b"body") is None
    finally:
        await provider.close()
