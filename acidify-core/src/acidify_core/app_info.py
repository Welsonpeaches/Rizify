from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppInfo:
    os: str
    kernel: str
    vendor_os: str
    current_version: str
    misc_bitmap: int
    pt_version: str
    sso_version: int
    package_name: str
    wt_login_sdk: str
    app_id: int
    sub_app_id: int
    app_client_version: int
    main_sig_map: int
    sub_sig_map: int
    nt_login_type: int

    @property
    def qua(self) -> str:
        platform = {"Windows": "WIN", "Mac": "MAC", "Linux": "LNX"}.get(self.os)
        if platform is None:
            raise ValueError(f"不支持的协议平台: {self.os}")
        return f"V1_{platform}_NQ_{self.current_version.replace('-', '_')}_GW_B"

    def to_json_object(self) -> dict[str, Any]:
        return {
            "Os": self.os,
            "Kernel": self.kernel,
            "VendorOs": self.vendor_os,
            "CurrentVersion": self.current_version,
            "MiscBitmap": self.misc_bitmap,
            "PtVersion": self.pt_version,
            "SsoVersion": self.sso_version,
            "PackageName": self.package_name,
            "WtLoginSdk": self.wt_login_sdk,
            "AppId": self.app_id,
            "SubAppId": self.sub_app_id,
            "AppClientVersion": self.app_client_version,
            "MainSigMap": self.main_sig_map,
            "SubSigMap": self.sub_sig_map,
            "NTLoginType": self.nt_login_type,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AppInfo:
        normalized = {str(key).lower(): item for key, item in value.items()}

        def pick(name: str, fallback: str) -> Any:
            return normalized.get(name, normalized.get(fallback))

        return cls(
            os=str(pick("os", "os")),
            kernel=str(pick("kernel", "kernel")),
            vendor_os=str(pick("vendoros", "vendor_os")),
            current_version=str(pick("currentversion", "current_version")),
            misc_bitmap=int(pick("miscbitmap", "misc_bitmap")),
            pt_version=str(pick("ptversion", "pt_version")),
            sso_version=int(pick("ssoversion", "sso_version")),
            package_name=str(pick("packagename", "package_name")),
            wt_login_sdk=str(pick("wtloginsdk", "wt_login_sdk")),
            app_id=int(pick("appid", "app_id")),
            sub_app_id=int(pick("subappid", "sub_app_id")),
            app_client_version=int(pick("appclientversion", "app_client_version")),
            main_sig_map=int(pick("mainsigmap", "main_sig_map")),
            sub_sig_map=int(pick("subsigmap", "sub_sig_map")),
            nt_login_type=int(pick("ntlogintype", "nt_login_type")),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> AppInfo:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("app-info.json 根节点必须是对象")
        return cls.from_mapping(value)

    def to_json_file(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_json_object(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


LINUX_39038 = AppInfo(
    os="Linux",
    kernel="Linux",
    vendor_os="linux",
    current_version="3.2.19-39038",
    misc_bitmap=32764,
    pt_version="2.0.0",
    sso_version=19,
    package_name="com.tencent.qq",
    wt_login_sdk="nt.wtlogin.0.0.1",
    app_id=1600001615,
    sub_app_id=537313942,
    app_client_version=39038,
    main_sig_map=169742560,
    sub_sig_map=0,
    nt_login_type=1,
)

LINUX_46494 = AppInfo(
    os="Linux",
    kernel="Linux",
    vendor_os="linux",
    current_version="3.2.26-46494",
    misc_bitmap=32764,
    pt_version="2.0.0",
    sso_version=19,
    package_name="com.tencent.qq",
    wt_login_sdk="nt.wtlogin.0.0.1",
    app_id=1600001615,
    sub_app_id=537345891,
    app_client_version=46494,
    main_sig_map=169742560,
    sub_sig_map=0,
    nt_login_type=1,
)

LINUX_53644 = AppInfo(
    os="Linux",
    kernel="Linux",
    vendor_os="linux",
    current_version="3.2.34-53644",
    misc_bitmap=32764,
    pt_version="2.0.0",
    sso_version=19,
    package_name="com.tencent.qq",
    wt_login_sdk="nt.wtlogin.0.0.1",
    app_id=1600001615,
    sub_app_id=537391664,
    app_client_version=53644,
    main_sig_map=169742560,
    sub_sig_map=0,
    nt_login_type=1,
)

MAC_52194 = AppInfo(
    os="Mac",
    kernel="Darwin",
    vendor_os="macos",
    current_version="7.0.0-52194",
    misc_bitmap=32764,
    pt_version="2.0.0",
    sso_version=23,
    package_name="com.tencent.qq",
    wt_login_sdk="nt.wtlogin.0.0.1",
    app_id=1600001602,
    sub_app_id=537379435,
    app_client_version=52194,
    main_sig_map=169742560,
    sub_sig_map=0,
    nt_login_type=5,
)

MAC_52892 = AppInfo(
    os="Mac",
    kernel="Darwin",
    vendor_os="macos",
    current_version="7.0.1-52892",
    misc_bitmap=32764,
    pt_version="2.0.0",
    sso_version=23,
    package_name="com.tencent.qq",
    wt_login_sdk="nt.wtlogin.0.0.1",
    app_id=1600001602,
    sub_app_id=537382843,
    app_client_version=52892,
    main_sig_map=169742560,
    sub_sig_map=0,
    nt_login_type=5,
)

bundled_pc_app_info: dict[str, AppInfo] = {
    "Linux/39038": LINUX_39038,
    "Linux/46494": LINUX_46494,
    "Linux/53644": LINUX_53644,
    "Mac/52194": MAC_52194,
    "Mac/52892": MAC_52892,
}


# Compatibility aliases matching the upstream names.
class Bundled:
    Linux_39038 = LINUX_39038
    Linux_46494 = LINUX_46494
    Linux_53644 = LINUX_53644
    Mac_52194 = MAC_52194
    Mac_52892 = MAC_52892
    Linux = LINUX_53644
    Mac = MAC_52892


AppInfo.Bundled = Bundled  # type: ignore[attr-defined]
