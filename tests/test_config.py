from __future__ import annotations

from pathlib import Path

import pytest
from rizify.cli import main
from rizify.config import ConfigError, load_config


def _write_config(tmp_path: Path, extra_protocol: str = "", *, version: str = "53644") -> Path:
    config = tmp_path / "rizify.toml"
    config.write_text(
        f"""
[protocol]
uin = 10001
os = "Linux"
version = "{version}"
signApiUrl = "http://127.0.0.1:8080/"
pcLagrangeSignToken = "$SIGN_TOKEN"
{extra_protocol}

[milky]
reportSelfMessage = true
preloadContacts = true
ffmpegPath = "ffmpeg"

[milky.http]
host = "127.0.0.1"
port = 3100
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
""",
        encoding="utf-8",
    )
    return config


def test_missing_config_generates_template_in_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([]) == 2
    config = tmp_path / "rizify.toml"
    assert config.is_file()
    text = config.read_text(encoding="utf-8")
    assert 'os = "Linux"' in text
    assert 'version = "53644"' in text
    assert 'signApiUrl = "http://127.0.0.1:8080/"' in text
    assert 'pcLagrangeSignToken = "$SIGN_TOKEN"' in text
    assert "已生成配置模板" in capsys.readouterr().err


def test_defaults_load_linux_53644(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret")
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    assert config.protocol.os == "Linux"
    assert config.protocol.version == "53644"
    assert config.protocol.sign_api_url == "http://127.0.0.1:8080/"
    assert config.app_info().qua == "V1_LNX_NQ_3.2.34_53644_GW_B"
    assert config.data_dir == tmp_path


@pytest.mark.parametrize("token", ["$SIGN_TOKEN", "${SIGN_TOKEN}"])
def test_token_environment_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret-token")
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        'pcLagrangeSignToken = "$SIGN_TOKEN"',
        f'pcLagrangeSignToken = "{token}"',
    )
    config_path.write_text(text, encoding="utf-8")
    assert load_config(config_path).protocol.pc_lagrange_sign_token == "secret-token"


def test_missing_token_environment_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGN_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="SIGN_TOKEN"):
        load_config(_write_config(tmp_path))


def test_literal_token_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGN_TOKEN", raising=False)
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        'pcLagrangeSignToken = "$SIGN_TOKEN"',
        'pcLagrangeSignToken = "legacy-literal-token"',
    )
    config_path.write_text(text, encoding="utf-8")
    assert load_config(config_path).protocol.pc_lagrange_sign_token == "legacy-literal-token"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/api/",
        "http://127.0.0.1:8080/api/sign/sec-sign",
        "http://127.0.0.1:8080/?x=1",
        "http://127.0.0.1:8080/#fragment",
    ],
)
def test_sign_url_must_be_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret")
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace("http://127.0.0.1:8080/", url)
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="根地址"):
        load_config(config_path)


def test_fetched_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret")
    with pytest.raises(ConfigError, match="fetched"):
        load_config(_write_config(tmp_path, version="fetched"))


def test_uin_must_be_positive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret")
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace("uin = 10001", "uin = 0")
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="uin"):
        load_config(config_path)


def test_custom_requires_app_info_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret")
    config_path = _write_config(tmp_path, version="custom")
    with pytest.raises(ConfigError, match=r"app-info\.json"):
        load_config(config_path)


def test_custom_app_info_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from acidify_core.app_info import Bundled

    monkeypatch.setenv("SIGN_TOKEN", "secret")
    Bundled.Linux_53644.to_json_file(tmp_path / "app-info.json")
    config = load_config(_write_config(tmp_path, version="custom"))
    assert config.app_info() == Bundled.Linux_53644


def test_unknown_protocol_key_reports_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGN_TOKEN", "secret")
    config_path = _write_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        "pcLagrangeSignToken", "unknownThing = 1\npcLagrangeSignToken"
    )
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="protocol 存在未知配置项: unknownThing"):
        load_config(config_path)
