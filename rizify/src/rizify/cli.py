from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .app import run_app
from .config import (
    ConfigError,
    default_config_path,
    load_config,
    write_template,
)
from .logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rizify",
        description="Rizify · 7sRef Milky 协议服务端",
    )
    parser.add_argument("--config", type=Path, help="rizify.toml 路径")
    parser.add_argument("--data-dir", type=Path, help="数据目录")
    parser.add_argument(
        "--version",
        action="version",
        version=f"Rizify {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = (args.config or default_config_path()).expanduser().resolve()
    if not config_path.exists():
        write_template(config_path)
        print(
            f"已生成配置模板：{config_path}\n"
            "请填写 [protocol].uin 并设置环境变量 SIGN_TOKEN，然后重新运行 rizify。",
            file=sys.stderr,
        )
        return 2
    try:
        config = load_config(config_path, args.data_dir)
    except FileNotFoundError as error:
        print(f"Rizify 配置错误：配置文件不存在：{error}", file=sys.stderr)
        return 2
    except (ConfigError, OSError, ValueError) as error:
        print(f"Rizify 配置错误：{error}", file=sys.stderr)
        return 2
    configure_logging(config.logging.level)
    try:
        return asyncio.run(run_app(config))
    except KeyboardInterrupt:
        return 130
    except ConfigError as error:
        print(f"Rizify 配置错误：{error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Rizify 启动失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
