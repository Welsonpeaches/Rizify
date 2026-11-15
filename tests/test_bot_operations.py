from __future__ import annotations

import pytest
from acidify_core import bot as bot_module
from acidify_core.bot import Bot


@pytest.mark.asyncio
async def test_get_pins_resolves_each_parsed_friend_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = object.__new__(Bot)

    async def fake_oidb_body(command: str, payload: bytes) -> bytes:
        assert command == "OidbSvcTrpcTcp.0x12b3_0"
        assert payload == b""
        return b"pins"

    async def fake_get_uin_by_uid(uid: int) -> int:
        return uid + 100

    def fake_parse_pinned_chats(body: bytes) -> tuple[list[int], list[int]]:
        assert body == b"pins"
        return [7, 9], [42]

    monkeypatch.setattr(bot, "_oidb_body", fake_oidb_body)
    monkeypatch.setattr(bot, "get_uin_by_uid", fake_get_uin_by_uid)
    monkeypatch.setattr(bot_module, "parse_pinned_chats", fake_parse_pinned_chats)

    result: tuple[list[int], list[int]] = await bot.get_pins()

    assert result == ([107, 109], [42])
