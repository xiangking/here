from __future__ import annotations

import json

import requests

from core.delivery.messaging.models import SendResult
from core.delivery.messaging.platforms.base import BaseMessagePlatform
from core.delivery.messaging.token_store import token_store


class FeishuMessagePlatform(BaseMessagePlatform):
    channel = "feishu"
    label = "Feishu"
    required_fields = ("app_id", "app_secret")
    target_fields = ("target", "open_id", "user_id", "email", "recipient")
    target_required = True

    def configured(self) -> tuple[bool, str]:
        return super().configured()

    def send(self, *, target: str, text: str) -> SendResult:
        token = self._fetch_token()
        if not token:
            return SendResult(self.channel, "failed", "missing_access_token")
        return self._post_json(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            {
                "receive_id": target,
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "msg_type": "text",
            },
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"receive_id_type": self._receive_id_type(target)},
        )

    def _fetch_token(self) -> str:
        cache_key = ("feishu", self._value("app_id"), self._value("app_secret"))
        return token_store.get_or_fetch(cache_key, self._request_token)

    def _request_token(self) -> tuple[str, int]:
        try:
            response = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self._value("app_id"), "app_secret": self._value("app_secret")},
                timeout=float(self.config.get("timeout") or 20),
                verify=self._verify(),
                proxies=self._proxies(),
            )
            data = response.json()
        except Exception:
            return "", 0
        if isinstance(data, dict) and data.get("code") == 0:
            token = str(data.get("tenant_access_token") or "")
            return token, int(data.get("expire") or 7200)
        return "", 0

    def _receive_id_type(self, target: str) -> str:
        configured = str(self.config.get("receive_id_type") or "").strip()
        if configured:
            return configured
        if target.startswith("ou_"):
            return "open_id"
        if "@" in target:
            return "email"
        return "open_id"

    def _api_error(self, response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, dict) and int(data.get("code") or 0) != 0:
            return f"feishu_error:{data}"
        return ""
