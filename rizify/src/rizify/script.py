from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from acidify_core.bot import Bot


class ScriptRuntime:
    def __init__(
        self,
        *,
        path: Path,
        timeout: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.path = path
        self.timeout = timeout
        self.logger = logger or logging.getLogger("rizify.script")
        self._context: Any = None
        self._callback: Any = None

    def start(self) -> None:
        try:
            import quickjs  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "script.enabled = true，但未安装 QuickJS；请运行 `uv sync` 安装项目依赖"
            ) from error
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        context = quickjs.Context()
        context.set_memory_limit(64 * 1024 * 1024)
        context.set_max_stack_size(2 * 1024 * 1024)
        source = self.path.read_text(encoding="utf-8")
        context.eval(source)
        callback = context.get("onMilkyEvent")
        if callback is None:
            callback = context.get("on_event")
        if callback is None or not callable(callback):
            raise ValueError(
                f"{self.path} 必须定义全局函数 onMilkyEvent(event)（或 on_event(event)）"
            )
        self._context = context
        self._callback = callback
        self.logger.info("QuickJS 脚本已加载: %s", self.path)

    async def dispatch(self, event: dict[str, Any]) -> None:
        if self._callback is None:
            return
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

        def invoke() -> None:
            assert self._callback is not None
            self._callback(payload)

        try:
            await asyncio.wait_for(asyncio.to_thread(invoke), timeout=self.timeout)
        except TimeoutError:
            self.logger.error("QuickJS 脚本处理事件超时（%.2fs）", self.timeout)
        except Exception:
            self.logger.exception("QuickJS 脚本处理事件失败")

    async def run(self, bot: Bot) -> None:
        async with bot.subscribe() as queue:
            while True:
                await self.dispatch(await queue.get())
