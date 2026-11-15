from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from acidify_core.app_info import AppInfo, bundled_pc_app_info

CONFIG_TEMPLATE = """\
# Rizify 0.2.0 配置
# 首次启动后填写 uin，再重新运行 `rizify`。

[protocol]
uin = 0
os = "Linux"
version = "53644"
signApiUrl = "http://127.0.0.1:8080/"
pcLagrangeSignToken = "$SIGN_TOKEN"

[milky]
reportSelfMessage = true
preloadContacts = true
ffmpegPath = "ffmpeg"

[milky.http]
host = "127.0.0.1"
port = 3000
prefix = "/api"

[milky.webhook]
endpoints = []

[logging]
level = "INFO"

[security]
accessToken = ""
corsOrigins = ["*"]

[debug]
enabled = false
"""


class ConfigError(ValueError):
    pass


@dataclass(slots=True)
class ProtocolConfig:
    uin: int
    os: str
    version: str
    sign_api_url: str
    pc_lagrange_sign_token: str


@dataclass(slots=True)
class HttpConfig:
    host: str = "127.0.0.1"
    port: int = 3000
    prefix: str = "/api"


@dataclass(slots=True)
class WebhookEndpoint:
    url: str
    access_token: str = ""


@dataclass(slots=True)
class MilkyConfig:
    http: HttpConfig = field(default_factory=HttpConfig)
    webhook_endpoints: list[WebhookEndpoint] = field(default_factory=list)
    report_self_message: bool = True
    preload_contacts: bool = True
    ffmpeg_path: str = "ffmpeg"


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(slots=True)
class SecurityConfig:
    access_token: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass(slots=True)
class DebugConfig:
    enabled: bool = False


@dataclass(slots=True)
class ScriptConfig:
    enabled: bool = False
    path: Path | None = None
    timeout: float = 1.0


@dataclass(slots=True)
class RizifyConfig:
    path: Path
    data_dir: Path
    protocol: ProtocolConfig
    milky: MilkyConfig = field(default_factory=MilkyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    script: ScriptConfig = field(default_factory=ScriptConfig)

    def app_info(self) -> AppInfo:
        if self.protocol.version == "custom":
            custom_path = self.data_dir / "app-info.json"
            if not custom_path.is_file():
                raise ConfigError(
                    f'protocol.version = "custom" 时，数据目录必须存在 app-info.json：{custom_path}'
                )
            try:
                return AppInfo.from_json_file(custom_path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ConfigError(f"无法读取 {custom_path}: {error}") from error
        key = f"{self.protocol.os}/{self.protocol.version}"
        app_info = bundled_pc_app_info.get(key)
        if app_info is None:
            supported = ", ".join(sorted(bundled_pc_app_info))
            raise ConfigError(f'未知协议版本 {key}。支持 {supported}，或设置 version = "custom"')
        return app_info


def default_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / "rizify.toml"


def write_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(CONFIG_TEMPLATE)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def load_config(
    config_path: Path | None = None,
    data_dir: Path | None = None,
) -> RizifyConfig:
    path = (config_path or default_config_path()).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: TOML 解析失败: {error}") from error
    root = _table(
        value, path, "root", {"protocol", "milky", "logging", "security", "debug", "script"}
    )
    protocol_table = _required_table(root, "protocol", "protocol")
    _reject_unknown(
        protocol_table,
        {"uin", "os", "version", "signApiUrl", "pcLagrangeSignToken"},
        "protocol",
    )
    uin = _integer(protocol_table, "uin", "protocol.uin", required=True)
    if uin <= 0:
        raise ConfigError("protocol.uin 必须大于 0；请填写真实账号后重新启动")
    os_name = _string(protocol_table, "os", "protocol.os", default="Linux")
    version = _string(protocol_table, "version", "protocol.version", default="53644")
    if version == "fetched":
        raise ConfigError('protocol.version = "fetched" 已移除，请使用 "53644" 或 "custom"')
    sign_api_url = _string(
        protocol_table,
        "signApiUrl",
        "protocol.signApiUrl",
        default="http://127.0.0.1:8080/",
    )
    normalized_sign_url = _validate_sign_url(sign_api_url)
    raw_token = _string(
        protocol_table,
        "pcLagrangeSignToken",
        "protocol.pcLagrangeSignToken",
        default="$SIGN_TOKEN",
    )
    token = _expand_token(raw_token, path)
    milky_table = _optional_table(root, "milky", "milky")
    milky = _parse_milky(milky_table)
    logging = _parse_logging(_optional_table(root, "logging", "logging"))
    security = _parse_security(_optional_table(root, "security", "security"))
    debug = _parse_debug(_optional_table(root, "debug", "debug"))
    script = _parse_script(_optional_table(root, "script", "script"), path.parent)
    resolved_data_dir = data_dir.expanduser().resolve() if data_dir is not None else path.parent
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    config = RizifyConfig(
        path=path,
        data_dir=resolved_data_dir,
        protocol=ProtocolConfig(uin, os_name, version, normalized_sign_url, token),
        milky=milky,
        logging=logging,
        security=security,
        debug=debug,
        script=script,
    )
    _ = config.app_info()
    return config


def _parse_milky(value: dict[str, Any]) -> MilkyConfig:
    _reject_unknown(
        value,
        {
            "http",
            "webhook",
            "reportSelfMessage",
            "preloadContacts",
            "ffmpegPath",
        },
        "milky",
    )
    http_table = _optional_table(value, "http", "milky.http")
    _reject_unknown(http_table, {"host", "port", "prefix"}, "milky.http")
    host = _string(http_table, "host", "milky.http.host", default="127.0.0.1")
    port = _integer(http_table, "port", "milky.http.port", required=False, default=3000)
    if not 1 <= port <= 65535:
        raise ConfigError("milky.http.port 必须在 1..65535 范围内")
    prefix = _string(http_table, "prefix", "milky.http.prefix", default="/api")
    if not prefix.startswith("/") or prefix.endswith("/") or "?" in prefix:
        raise ConfigError("milky.http.prefix 必须以 / 开头、不能以 / 结尾且不能包含查询参数")
    webhook_table = _optional_table(value, "webhook", "milky.webhook")
    _reject_unknown(webhook_table, {"endpoints"}, "milky.webhook")
    endpoints_raw = webhook_table.get("endpoints", [])
    if not isinstance(endpoints_raw, list):
        raise ConfigError("milky.webhook.endpoints 必须是数组")
    endpoints: list[WebhookEndpoint] = []
    for index, item in enumerate(endpoints_raw):
        key = f"milky.webhook.endpoints[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{key} 必须是表")
        _reject_unknown(item, {"url", "accessToken"}, key)
        url = _string(item, "url", f"{key}.url", required=True)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ConfigError(f"{key}.url 必须是有效的 HTTP(S) URL")
        token = _string(item, "accessToken", f"{key}.accessToken", default="")
        endpoints.append(WebhookEndpoint(url, token))
    return MilkyConfig(
        http=HttpConfig(host, port, prefix),
        webhook_endpoints=endpoints,
        report_self_message=_boolean(
            value, "reportSelfMessage", "milky.reportSelfMessage", default=True
        ),
        preload_contacts=_boolean(value, "preloadContacts", "milky.preloadContacts", default=True),
        ffmpeg_path=_string(value, "ffmpegPath", "milky.ffmpegPath", default="ffmpeg"),
    )


def _parse_logging(value: dict[str, Any]) -> LoggingConfig:
    _reject_unknown(value, {"level"}, "logging")
    level = _string(value, "level", "logging.level", default="INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("logging.level 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL")
    return LoggingConfig(level)


def _parse_security(value: dict[str, Any]) -> SecurityConfig:
    _reject_unknown(value, {"accessToken", "corsOrigins"}, "security")
    access_token = _string(value, "accessToken", "security.accessToken", default="")
    origins_raw = value.get("corsOrigins", ["*"])
    if not isinstance(origins_raw, list) or not all(isinstance(item, str) for item in origins_raw):
        raise ConfigError("security.corsOrigins 必须是字符串数组")
    return SecurityConfig(access_token, list(origins_raw))


def _parse_debug(value: dict[str, Any]) -> DebugConfig:
    _reject_unknown(value, {"enabled"}, "debug")
    return DebugConfig(_boolean(value, "enabled", "debug.enabled", default=False))


def _parse_script(value: dict[str, Any], base: Path) -> ScriptConfig:
    _reject_unknown(value, {"enabled", "path", "timeout"}, "script")
    enabled = _boolean(value, "enabled", "script.enabled", default=False)
    raw_path = _string(value, "path", "script.path", default="")
    path = None
    if raw_path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = (base / path).resolve()
    timeout_raw = value.get("timeout", 1.0)
    if not isinstance(timeout_raw, (int, float)) or isinstance(timeout_raw, bool):
        raise ConfigError("script.timeout 必须是数字")
    if enabled and path is None:
        raise ConfigError("script.enabled = true 时必须设置 script.path")
    return ScriptConfig(enabled, path, float(timeout_raw))


TOKEN_PATTERN = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")


def _expand_token(value: str, config_path: Path) -> str:
    match = TOKEN_PATTERN.fullmatch(value)
    if match is None:
        token = value.strip()
        if token:
            return token
        raise ConfigError(f"protocol.pcLagrangeSignToken 不能为空（{config_path}）")
    name = match.group(1) or match.group(2)
    token = os.environ.get(name, "")
    if not token:
        raise ConfigError(f"环境变量 {name} 未设置或为空，无法配置签名令牌")
    return token


def _validate_sign_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("protocol.signApiUrl 必须是 http(s) 根地址")
    if parts.query or parts.fragment:
        raise ConfigError("protocol.signApiUrl 必须是根地址，不能包含 query 或 fragment")
    if parts.path not in ("", "/"):
        raise ConfigError(
            "protocol.signApiUrl 必须是根地址；Rizify 会自行追加 api/sign/sec-sign，"
            "不要写成 /api/ 或 /api/sign/sec-sign"
        )
    if parts.username or parts.password:
        raise ConfigError("protocol.signApiUrl 不能包含用户名或密码")
    return f"{parts.scheme}://{parts.netloc}/"


def _required_table(parent: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    if key not in parent:
        raise ConfigError(f"缺少配置项 {path}")
    return _table(parent[key], None, path, None)


def _optional_table(parent: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    if key not in parent:
        return {}
    return _table(parent[key], None, path, None)


def _table(
    value: Any,
    source: Path | None,
    path: str,
    allowed: set[str] | None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        prefix = f"{source}: " if source is not None else ""
        raise ConfigError(f"{prefix}{path} 必须是表")
    if allowed is not None:
        _reject_unknown(value, allowed, path)
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"{path} 存在未知配置项: {', '.join(unknown)}")


def _string(
    value: dict[str, Any],
    key: str,
    path: str,
    *,
    required: bool = False,
    default: str = "",
) -> str:
    if key not in value:
        if required:
            raise ConfigError(f"缺少配置项 {path}")
        return default
    item = value[key]
    if not isinstance(item, str):
        raise ConfigError(f"{path} 必须是字符串")
    return item


def _integer(
    value: dict[str, Any],
    key: str,
    path: str,
    *,
    required: bool,
    default: int = 0,
) -> int:
    if key not in value:
        if required:
            raise ConfigError(f"缺少配置项 {path}")
        return default
    item = value[key]
    if not isinstance(item, int) or isinstance(item, bool):
        raise ConfigError(f"{path} 必须是整数")
    return item


def _boolean(
    value: dict[str, Any],
    key: str,
    path: str,
    *,
    default: bool,
) -> bool:
    if key not in value:
        return default
    item = value[key]
    if not isinstance(item, bool):
        raise ConfigError(f"{path} 必须是布尔值")
    return item
