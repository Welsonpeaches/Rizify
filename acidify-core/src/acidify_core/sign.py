from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

import httpx

from .exceptions import SignError

LINUX_COMMAND_WHITELIST = {
    "trpc.o3.ecdh_access.EcdhAccess.SsoEstablishShareKey",
    "trpc.o3.ecdh_access.EcdhAccess.SsoSecureAccess",
    "trpc.o3.report.Report.SsoReport",
    "trpc.o3.ecdh_access.EcdhAccess.SsoSecureA2Access",
    "trpc.o3.ecdh_access.EcdhAccess.SsoSecureA2Establish",
    "MessageSvc.PbSendMsg",
    "trpc.group.long_msg_interface.MsgService.SsoRecvLongMsg",
    "trpc.group.long_msg_interface.MsgService.SsoSendLongMsg",
    "trpc.msg.msg_svc.MsgService.SsoReadedReport",
    "trpc.msg.msg_svc.MsgService.SsoC2CRecallMsg",
    "wtlogin.trans_emp",
    "wtlogin.login",
    "trpc.login.ecdh.EcdhService.SsoKeyExchange",
    "trpc.login.ecdh.EcdhService.SsoNTLoginPasswordLogin",
    "trpc.login.ecdh.EcdhService.SsoNTLoginEasyLogin",
    "trpc.login.ecdh.EcdhService.SsoNTLoginPasswordLoginNewDevice",
    "trpc.login.ecdh.EcdhService.SsoNTLoginEasyLoginUnusualDevice",
    "trpc.login.ecdh.EcdhService.SsoNTLoginPasswordLoginUnusualDevice",
    "trpc.login.ecdh.EcdhService.SsoNTLoginAuthLogin",
    "trpc.login.ecdh.EcdhService.SsoNTLoginAuthCodeLogin",
    "trpc.qqhb.qqhb_proxy.Handler.sso_handle",
    "QQConnectLogin.auth",
    "QQConnectLogin.pre_auth",
    "OidbSvcTrpcTcp.0x11ec_1",
    "OidbSvcTrpcTcp.0x758_1",
    "OidbSvcTrpcTcp.0x7c2_5",
    "OidbSvcTrpcTcp.0x10db_1",
    "OidbSvcTrpcTcp.0x8a1_7",
    "OidbSvcTrpcTcp.0x89a_0",
    "OidbSvcTrpcTcp.0x89a_15",
    "OidbSvcTrpcTcp.0x88d_0",
    "OidbSvcTrpcTcp.0x88d_14",
    "OidbSvcTrpcTcp.0x112a_1",
    "OidbSvcTrpcTcp.0x112a_2",
    "OidbSvcTrpcTcp.0x587_74",
    "OidbSvcTrpcTcp.0x1100_1",
    "OidbSvcTrpcTcp.0x1102_1",
    "OidbSvcTrpcTcp.0x1103_1",
    "OidbSvcTrpcTcp.0x1107_1",
    "OidbSvcTrpcTcp.0x1105_1",
    "OidbSvcTrpcTcp.0xf88_1",
    "OidbSvcTrpcTcp.0xf89_1",
    "OidbSvcTrpcTcp.0xf57_1",
    "OidbSvcTrpcTcp.0xf57_106",
    "OidbSvcTrpcTcp.0xf57_9",
    "OidbSvcTrpcTcp.0xf55_1",
    "OidbSvcTrpcTcp.0xf67_1",
    "OidbSvcTrpcTcp.0xf67_5",
    "OidbSvcTrpcTcp.0x6d9_4",
    "trpc.login.ecdh.EcdhService.SsoQRLoginGenQr",
    "ConnAuthSvr.fast_qq_login",
    "ConnAuthSvr.sdk_auth_api",
    "ConnAuthSvr.sdk_auth_api_emp",
    "MsgProxy.SendMsg",
    "OidbSvcTrpcTcp.0x101e_1",
    "OidbSvcTrpcTcp.0x101e_2",
    "OidbSvcTrpcTcp.0xf65_1",
    "OidbSvcTrpcTcp.0xf65_10",
    "OidbSvcTrpcTcp.0xf6e_1",
    "OidbSvcTrpcTcp.0xfa5_1",
    "trpc.group_pro.msgproxy.sendmsg",
    "trpc.passwd.manager.PasswdManager.SetPasswd",
    "trpc.passwd.manager.PasswdManager.VerifyPasswd",
    "wtlogin_device.login",
    "wtlogin_device.tran_sim_emp",
    "trpc.login.ecdh.EcdhService.SsoNTLoginTGTExchangeFastLogin",
    "trpc.ecom.api_gateway.ApiGateway.SsoForward",
    "OidbSvcTrpcTcp.0x917b_1",
    "OidbSvcTcp.0x102a",
    "OidbSvcTrpcTcp.0x102a_0",
    "OidbSvcTrpcTcp.0x102a_1",
    "OidbSvc.0xcd5",
    "OidbSvcTrpcTcp.0xcd5",
    "OidbSvcTrpcTcp.0xcd5_0",
    "OidbSvc.0xdc2_34",
    "OidbSvcTrpcTcp.0xdc2_58",
    "OidbSvcTrpcTcp.0xdc2_59",
    "OidbSvcTrpcTcp.0x10c8_2",
    "OidbSvcTrpcTcp.0x93d7_1",
    "OidbSvc.0xb77_9",
    "OidbSvcTrpcTcp.0x112e_1",
    "OidbSvcTrpcTcp.0x10c8_1",
    "OidbSvcTrpcTcp.0x962a_1",
    "OidbSvcTrpcTcp.0x9409_7",
    "OidbSvcTrpcTcp.0x9409_10",
    "OidbSvcTrpcTcp.0x9409_11",
    "OidbSvcTrpcTcp.0x9409_12",
    "OidbSvcTrpcTcp.0x9409_13",
    "OidbSvcTrpcTcp.0x9409_14",
    "OidbSvcTrpcTcp.0x9409_15",
    "OidbSvcTrpcTcp.0x9409_16",
    "OidbSvcTrpcTcp.0x9409_18",
    "OidbSvcTrpcTcp.0x101b_1",
    "trpc.login.ecdh.EcdhService.SsoNTLoginRefreshTicket",
}

MAC_COMMAND_WHITELIST = {
    "AvatarInfoSvr.QQHeadUrlReq",
    "MessageSvc.PbSendMsg",
    "MsgProxy.SendMsg",
    "trpc.group_pro.msgproxy.sendmsg",
    "wtlogin.login",
    "wtlogin.trans_emp",
    "ConnAuthSvr.fast_qq_login",
    "ConnAuthSvr.sdk_auth_api",
    "ConnAuthSvr.sdk_auth_api_emp",
    "trpc.login.ecdh.EcdhService.SsoQRLoginGenQr",
}


@dataclass(slots=True)
class SignResult:
    sign: bytes
    token: bytes
    extra: bytes


class SignProvider(Protocol):
    async def sign(self, command: str, sequence: int, source: bytes) -> SignResult | None: ...


class LagrangeUrlSignProvider:
    def __init__(self, url: str, token: str, uin: int, guid: str, qua: str) -> None:
        base = url if url.endswith("/") else f"{url}/"
        self.sign_url = urljoin(base, "api/sign/sec-sign")
        self.token = token
        self.uin = uin
        self.guid = guid
        self.qua = qua
        self._client = httpx.AsyncClient(timeout=15.0, http2=True)

    async def sign(self, command: str, sequence: int, source: bytes) -> SignResult | None:
        if self.qua.startswith("V1_LNX_") and command not in LINUX_COMMAND_WHITELIST:
            return None
        if self.qua.startswith("V1_MAC_") and command not in MAC_COMMAND_WHITELIST:
            return None
        response = await self._client.post(
            self.sign_url,
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "command": command,
                "seq": sequence,
                "body": source.hex(),
                "uin": self.uin,
                "guid": self.guid,
                "qua": self.qua,
            },
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise SignError(response.status_code, response.text[:300]) from error
        if not isinstance(payload, dict):
            raise SignError(response.status_code, "签名服务返回了非对象响应")
        code = int(payload.get("code", response.status_code))
        message = str(payload.get("message") or "")
        value = payload.get("value")
        if response.status_code >= 400 or code != 0 or not isinstance(value, dict):
            raise SignError(code, message or f"HTTP {response.status_code}")
        try:
            return SignResult(
                sign=bytes.fromhex(str(value["sec_sign"])),
                token=bytes.fromhex(str(value["sec_token"])),
                extra=bytes.fromhex(str(value["sec_extra"])),
            )
        except (KeyError, ValueError) as error:
            raise SignError(code, "签名服务响应缺少有效的 sec_sign/sec_token/sec_extra") from error

    async def close(self) -> None:
        await self._client.aclose()
