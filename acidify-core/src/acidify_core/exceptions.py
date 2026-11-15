from __future__ import annotations


class AcidifyError(Exception):
    """Base error for the protocol core."""


class ConfigError(AcidifyError):
    pass


class SignError(AcidifyError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"签名服务错误 {code}: {message}" if message else f"签名服务错误 {code}")
        self.code = code
        self.message = message


class WtLoginError(AcidifyError):
    def __init__(self, code: int, tag: str, message: str) -> None:
        super().__init__(f"{tag or '登录失败'} (code={code}): {message}")
        self.code = code
        self.tag = tag
        self.message = message


class ServiceError(AcidifyError):
    def __init__(self, command: str, ret_code: int, extra: str) -> None:
        detail = f" ({extra})" if extra else ""
        super().__init__(f"服务 {command} 返回错误码 {ret_code}{detail}")
        self.command = command
        self.ret_code = ret_code
        self.extra = extra


class BotOnlineError(AcidifyError):
    pass


class MessageSendError(AcidifyError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"消息发送失败 {code}: {message}")
        self.code = code
        self.message = message


class SessionRenewalError(AcidifyError):
    pass
