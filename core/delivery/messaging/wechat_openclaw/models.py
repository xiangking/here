from __future__ import annotations

from dataclasses import dataclass


DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_BOT_TYPE = "3"


@dataclass(frozen=True)
class WeChatAccount:
    account_id: str
    token: str
    base_url: str = DEFAULT_BASE_URL
    user_id: str = ""


@dataclass(frozen=True)
class LoginStartResult:
    session_key: str
    qrcode: str
    qrcode_url: str
    message: str = ""


@dataclass(frozen=True)
class LoginPollResult:
    status: str
    message: str = ""
    account: WeChatAccount | None = None
    redirect_base_url: str = ""


@dataclass(frozen=True)
class WeChatInboundMessage:
    from_user_id: str
    to_user_id: str = ""
    context_token: str = ""
    text: str = ""
    message_id: str = ""
    item_types: tuple[int, ...] = ()
