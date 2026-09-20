from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    DeliveryAdapterRegistry,
    DeliveryCapabilityProbe,
    DeliveryRouter,
    DesktopDeliveryAdapter,
    MessageSender,
    MessagingConfig,
    MessagingDeliveryAdapter,
    base64,
    create_default_registry,
    discover_next_private_chat_id,
    io,
    wechat_api,
    wechat_state,
)


def wechat_login_start(self, payload: dict[str, Any]) -> dict[str, Any]:
    login = wechat_api.start_login(base_url=str(payload.get("base_url") or "").strip() or "https://ilinkai.weixin.qq.com")
    import qrcode

    image = qrcode.make(login.qrcode_url or login.qrcode)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {
        **hooks.model_json(login.__dict__),
        "qr_data_url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


def wechat_login_poll(self, payload: dict[str, Any]) -> dict[str, Any]:
    polled = wechat_api.poll_login(
        qrcode=str(payload.get("qrcode") or ""),
        base_url=str(payload.get("base_url") or "").strip() or "https://ilinkai.weixin.qq.com",
        timeout=8,
    )
    if polled.account is not None:
        wechat_state.replace_accounts(polled.account)
        self._restart_chat_platform_bridge()
    return hooks.model_json(polled.__dict__)


def wechat_status(self) -> dict[str, Any]:
    accounts = []
    for account_id in wechat_state.list_account_ids():
        account = wechat_state.load_account(account_id)
        if account is None:
            continue
        accounts.append({
            "account_id": account.account_id,
            "base_url": account.base_url,
            "user_id": account.user_id,
            "recipients": wechat_state.list_context_user_ids(account.account_id),
        })
    return {"accounts": accounts}


def telegram_discover(self, payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    if not token:
        raise ValueError("请先填写 Telegram Bot Token。")
    discovered = discover_next_private_chat_id(token, timeout_seconds=45)
    return hooks.model_json(discovered.__dict__)


def list_models(self, payload: dict[str, Any]) -> dict[str, Any]:
    from openai import OpenAI

    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    api_key = str(payload.get("api_key") or "").strip() or "unused"
    client = OpenAI(api_key=api_key, base_url=base_url or None)
    models = sorted(
        str(model.id)
        for model in client.models.list().data
        if str(getattr(model, "id", "") or "").strip()
    )
    return {"models": models}


def save_messaging(self, payload: dict[str, Any]) -> dict[str, Any]:
    config = MessagingConfig(payload)
    config.save()
    self.sender = MessageSender(config=config, registry=create_default_registry(self._emit_dialog))
    self.delivery = DeliveryAdapterRegistry(
        DesktopDeliveryAdapter(self._emit_dialog),
        MessagingDeliveryAdapter(self.sender),
    )
    self.delivery_router = DeliveryRouter(self.config, DeliveryCapabilityProbe(self.config))
    self._restart_chat_platform_bridge()
    return {
        key: hooks.model_json(value)
        for key, value in DeliveryCapabilityProbe(self.config).probe().items()
    }
