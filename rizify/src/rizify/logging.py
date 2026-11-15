from __future__ import annotations

import logging
import sys
from datetime import datetime

RESET = "\033[0m"
BOLD = "\033[1m"
GRAY = "\033[90m"
BRIGHT_WHITE = "\033[97m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_RED = "\033[91m"

TAG_ALIASES = {
    "acidify_core.bot": "Rizify/Bot",
    "acidify_core.transport": "Rizify/Packet",
    "acidify_core.sign": "Rizify/PRiSM",
    "rizify.config": "Rizify/Config",
    "rizify.session": "Rizify/Session",
    "rizify.app": "Rizify/Core",
    "rizify.milky.server": "Milky/Server",
    "rizify.milky.http": "Milky/Http",
    "rizify.milky.websocket": "Milky/WS",
    "rizify.milky.sse": "Milky/SSE",
    "rizify.milky.webhook": "Milky/Webhook",
    "rizify.script": "Rizify/Script",
}


def format_tag(tag: str) -> str:
    if tag in TAG_ALIASES:
        return TAG_ALIASES[tag]
    if tag.startswith("rizify."):
        return f"Rizify/{tag.removeprefix('rizify.')}"
    if tag.startswith("acidify_core."):
        return f"Rizify/{tag.removeprefix('acidify_core.')}"
    return tag


class RizifyFormatter(logging.Formatter):
    def __init__(self, *, color: bool = True) -> None:
        super().__init__()
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        level_name = {
            logging.DEBUG: "DEBUG",
            logging.INFO: " INFO",
            logging.WARNING: " WARN",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "ERROR",
        }.get(record.levelno, " INFO")
        tag = format_tag(record.name).ljust(16)
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        stamp = datetime.now().strftime("%H:%M:%S")
        if not self.color:
            return f"{stamp} {level_name} │ {tag} │ {message}"
        level_color = {
            logging.DEBUG: BRIGHT_CYAN,
            logging.INFO: BRIGHT_GREEN,
            logging.WARNING: BRIGHT_YELLOW,
            logging.ERROR: BRIGHT_RED,
            logging.CRITICAL: BRIGHT_RED,
        }.get(record.levelno, BRIGHT_GREEN)
        tag_color = GRAY if record.levelno == logging.DEBUG else BRIGHT_WHITE
        return (
            f"{BOLD}{BRIGHT_GREEN}{stamp}{RESET} "
            f"{level_color}{level_name}{RESET}"
            f"{GRAY} │ {RESET}"
            f"{tag_color}{tag}{RESET}"
            f"{GRAY} │ {RESET}"
            f"{message}"
        )


def configure_logging(level: str = "INFO", *, color: bool | None = None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RizifyFormatter(color=sys.stderr.isatty() if color is None else color))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
    for noisy in ("httpx", "httpcore", "asyncio", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def protocol_logger() -> logging.Logger:
    return logging.getLogger("rizify.protocol")
