from __future__ import annotations

import asyncio
import contextlib
import logging

from acidify_core.bot import Bot
from acidify_core.oidb import UserInfo
from acidify_core.sign import LagrangeUrlSignProvider

from . import __version__
from .config import RizifyConfig
from .logging import protocol_logger
from .milky import MilkyServer
from .script import ScriptRuntime
from .session import SESSION_FILENAME, load_session

BANNER = """\
.-----------------------------------------.
|   ____  _         __                    |
|  / __ \\(_)_______/ /_  __  __           |
| / /_/ / /___/ _  / / / / / /            |
|/ _, _/ /  / /_/ / /_/ /_/ /             |
|/_/ |_/_/  /_/  /_/\\__, /_. /             |
|                  /____/                 |
|  Rizify · 7sRef Milky Protocol Server   |
|  Acidify + Python · GPL-3.0-only        |
'-----------------------------------------'
"""


class RizifyApp:
    def __init__(self, config: RizifyConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("rizify.app")
        self.session = load_session(
            config.data_dir,
            config.protocol.uin,
            logging.getLogger("rizify.session"),
        )
        self.app_info = config.app_info()
        self.sign_provider = LagrangeUrlSignProvider(
            config.protocol.sign_api_url,
            config.protocol.pc_lagrange_sign_token,
            config.protocol.uin,
            self.session.guid.hex(),
            self.app_info.qua,
        )
        self.bot = Bot(
            uin=config.protocol.uin,
            app_info=self.app_info,
            sign_provider=self.sign_provider,
            session=self.session,
            session_path=config.data_dir / SESSION_FILENAME,
            logger=logging.getLogger("acidify_core.bot"),
        )
        self.milky = MilkyServer(bot=self.bot, config=config, version=__version__)
        self.script: ScriptRuntime | None = None
        self.self_info: UserInfo | None = None

    async def run(self) -> int:
        print(BANNER, flush=True)
        logger = protocol_logger()
        logger.info(
            "使用协议 %s %s (AppId: %s)",
            self.app_info.os,
            self.app_info.current_version,
            self.app_info.sub_app_id,
        )
        logger.info("QUA: %s", self.app_info.qua)
        logger.info("碎片签发端点: %sapi/sign/sec-sign", self.config.protocol.sign_api_url)
        logger.info("数据目录: %s", self.config.data_dir)
        if self.config.script.enabled and self.config.script.path is not None:
            self.script = ScriptRuntime(
                path=self.config.script.path,
                timeout=self.config.script.timeout,
                logger=logging.getLogger("rizify.script"),
            )
            self.script.start()
        await self.milky.start()
        script_task: asyncio.Task[None] | None = None
        if self.script is not None:
            script_task = asyncio.create_task(self.script.run(self.bot), name="rizify-quickjs")
        try:
            await self.bot.login(
                qr_path=self.config.data_dir / "qrcode.png",
                query_interval=3.0,
            )
            if self.config.milky.preload_contacts:
                await asyncio.gather(
                    self.bot.fetch_friends(),
                    self.bot.fetch_groups(),
                )
            with contextlib.suppress(Exception):
                self.self_info = await self.bot.fetch_user_info(self.bot.session.uin)
            nickname = self.self_info.nickname if self.self_info else ""
            self.logger.info(
                "登录完成：%s%s",
                self.bot.session.uin,
                f" ({nickname})" if nickname else "",
            )
            await asyncio.Event().wait()
        finally:
            if script_task is not None:
                script_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await script_task
            await self.milky.stop()
            await self.bot.close()
        return 0


async def run_app(config: RizifyConfig) -> int:
    app = RizifyApp(config)

    def stop() -> None:
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            import signal

            loop.add_signal_handler(getattr(signal, signal_name), stop)
    try:
        return await app.run()
    except asyncio.CancelledError:
        return 130
