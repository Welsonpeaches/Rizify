from __future__ import annotations

import logging
from pathlib import Path

from acidify_core.session import SessionStore

SESSION_FILENAME = "session.json"
LEGACY_SESSION_FILENAME = "session-store.json"


def load_session(
    data_dir: Path,
    uin: int,
    logger: logging.Logger | None = None,
) -> SessionStore:
    log = logger or logging.getLogger("rizify.session")
    session_path = data_dir / SESSION_FILENAME
    legacy_path = data_dir / LEGACY_SESSION_FILENAME
    if session_path.is_file():
        session = SessionStore.from_file(session_path)
        if session.uin not in (0, uin):
            raise ValueError(
                f"{session_path} 属于账号 {session.uin}，与配置的 uin {uin} 不一致；"
                "请更换数据目录或删除旧会话后重新扫码"
            )
        return session
    if legacy_path.is_file():
        log.info("发现旧会话 %s，正在迁移到 %s", legacy_path, session_path)
        session = SessionStore.from_file(legacy_path)
        if session.uin not in (0, uin):
            raise ValueError(f"{legacy_path} 属于账号 {session.uin}，与配置的 uin {uin} 不一致")
        session.save(session_path)
        return session
    return SessionStore()
