from __future__ import annotations

from pathlib import Path

from acidify_core.app_info import Bundled, bundled_pc_app_info


def test_linux_53644_is_the_default_and_has_exact_qua() -> None:
    app_info = Bundled.Linux_53644
    assert Bundled.Linux is app_info
    assert app_info.os == "Linux"
    assert app_info.current_version == "3.2.34-53644"
    assert app_info.app_id == 1600001615
    assert app_info.sub_app_id == 537391664
    assert app_info.app_client_version == 53644
    assert app_info.main_sig_map == 169742560
    assert app_info.qua == "V1_LNX_NQ_3.2.34_53644_GW_B"


def test_bundled_versions_remain_available() -> None:
    assert bundled_pc_app_info["Linux/53644"] is Bundled.Linux_53644
    assert bundled_pc_app_info["Linux/46494"] is Bundled.Linux_46494
    assert bundled_pc_app_info["Linux/39038"] is Bundled.Linux_39038
    assert bundled_pc_app_info["Mac/52194"] is Bundled.Mac_52194
    assert bundled_pc_app_info["Mac/52892"] is Bundled.Mac_52892


def test_app_info_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "app-info.json"
    Bundled.Linux_53644.to_json_file(path)
    loaded = type(Bundled.Linux_53644).from_json_file(path)
    assert loaded == Bundled.Linux_53644
