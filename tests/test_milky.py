from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from acidify_core.app_info import LINUX_53644
from acidify_core.bot import Bot
from acidify_core.session import SessionStore
from aiohttp.test_utils import TestClient, TestServer
from rizify.config import (
    HttpConfig,
    MilkyConfig,
    ProtocolConfig,
    RizifyConfig,
    SecurityConfig,
)
from rizify.milky.server import API_PATHS, MilkyServer


class FakeBot:
    def __init__(self) -> None:
        self.session = SessionStore(uin=10001)
        self.app_info = LINUX_53644
        self.is_online = True
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    async def emit(self, event: dict[str, Any]) -> None:
        for queue in self._queues:
            queue.put_nowait(event)


def make_config(tmp_path: Path, *, access_token: str = "") -> RizifyConfig:
    return RizifyConfig(
        path=tmp_path / "rizify.toml",
        data_dir=tmp_path,
        protocol=ProtocolConfig(
            uin=10001,
            os="Linux",
            version="53644",
            sign_api_url="http://127.0.0.1:8080/",
            pc_lagrange_sign_token="token",
        ),
        milky=MilkyConfig(http=HttpConfig("127.0.0.1", 3100, "/api")),
        security=SecurityConfig(access_token=access_token),
    )


async def test_impl_info_and_validation(tmp_path: Path) -> None:
    server = MilkyServer(
        bot=cast(Bot, FakeBot()),
        config=make_config(tmp_path),
        version="0.2.0",
    )
    async with TestClient(TestServer(server.create_app())) as client:
        response = await client.post("/api/get_impl_info", json={})
        assert response.status == 200
        payload = await response.json()
        assert payload["retcode"] == 0
        assert payload["data"]["impl_name"] == "Rizify"
        assert payload["data"]["impl_version"] == "0.2.0"
        assert payload["data"]["qq_protocol_version"] == "3.2.34-53644"

        response = await client.post(
            "/api/get_user_profile",
            data="{",
            headers={"Content-Type": "application/json"},
        )
        payload = await response.json()
        assert response.status == 200
        assert payload["status"] == "failed"
        assert payload["retcode"] == -400

        response = await client.post("/api/get_user_profile", json={})
        payload = await response.json()
        assert payload["retcode"] == -400


async def test_auth_cors_and_prefix(tmp_path: Path) -> None:
    server = MilkyServer(
        bot=cast(Bot, FakeBot()),
        config=make_config(tmp_path, access_token="secret"),
        version="0.2.0",
    )
    async with TestClient(TestServer(server.create_app())) as client:
        response = await client.post("/api/get_impl_info", json={})
        assert response.status == 401

        response = await client.post(
            "/api/get_impl_info",
            json={},
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status == 200

        response = await client.options(
            "/api/get_impl_info",
            headers={"Origin": "https://example.invalid"},
        )
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == "*"

        response = await client.post("/ppp/get_impl_info", json={})
        assert response.status == 405


async def test_all_api_paths_are_registered(tmp_path: Path) -> None:
    server = MilkyServer(
        bot=cast(Bot, FakeBot()),
        config=make_config(tmp_path),
        version="0.2.0",
    )
    app = server.create_app()
    registered = {str(getattr(route.resource, "canonical", "")) for route in app.router.routes()}
    registered.discard("")
    registered = {path for path in registered if path.startswith("/api/")}
    assert registered == {f"/api{path}" for path in API_PATHS}


async def test_websocket_event_stream(tmp_path: Path) -> None:
    bot = FakeBot()
    server = MilkyServer(
        bot=cast(Bot, bot),
        config=make_config(tmp_path),
        version="0.2.0",
    )
    async with TestClient(TestServer(server.create_app())) as client:
        websocket = await client.ws_connect("/event")
        await bot.emit(
            {
                "event_type": "bot_online",
                "time": 1,
                "self_id": 10001,
                "data": {},
            }
        )
        message = await asyncio.wait_for(websocket.receive(), timeout=2)
        assert message.type.name == "TEXT"
        payload = json.loads(message.data)
        assert payload["event_type"] == "bot_online"
        await websocket.close()


async def test_api_rejects_offline_bot(tmp_path: Path) -> None:
    bot = FakeBot()
    bot.is_online = False
    server = MilkyServer(
        bot=cast(Bot, bot),
        config=make_config(tmp_path),
        version="0.2.0",
    )
    async with TestClient(TestServer(server.create_app())) as client:
        response = await client.post("/api/get_impl_info", json={})
        payload = await response.json()
        assert payload["retcode"] == -403
