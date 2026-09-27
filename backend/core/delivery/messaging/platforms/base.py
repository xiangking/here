from __future__ import annotations

import time
from typing import Any

import requests

from core.delivery.messaging.models import SendResult


class BaseMessagePlatform:
    channel = ""
    label = ""
    required_fields: tuple[str, ...] = ()
    target_fields: tuple[str, ...] = ("target", "recipient")
    target_required = True
    retryable_statuses = {408, 429, 500, 502, 503, 504}

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def configured(self) -> tuple[bool, str]:
        missing = [field for field in self.required_fields if not self._value(field)]
        if missing:
            return False, f"missing_config:{','.join(missing)}"
        if self.target_required and not self.default_target():
            return False, "missing_target"
        return True, "ready"

    def default_target(self) -> str:
        for field in self.target_fields:
            value = self._value(field)
            if value:
                return value
        return ""

    def send(self, *, target: str, text: str) -> SendResult:
        raise NotImplementedError

    def send_image(self, *, target: str, image_path: str, caption: str = "") -> SendResult:
        return SendResult(self.channel, "failed", "unsupported_image")

    def send_audio(self, *, target: str, audio_path: str, caption: str = "") -> SendResult:
        return SendResult(self.channel, "failed", "unsupported_audio")

    def _value(self, key: str) -> str:
        return str(self.config.get(key) or "").strip()

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        ok_statuses: tuple[int, ...] = (200, 201, 202, 204),
    ) -> SendResult:
        attempts = max(1, int(self.config.get("retries") or 2) + 1)
        response = None
        last_error = ""
        for attempt in range(attempts):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    params=params,
                    json=payload,
                    timeout=float(self.config.get("timeout") or 20),
                    verify=self._verify(),
                    proxies=self._proxies(),
                )
            except requests.RequestException as exc:
                last_error = f"request_error:{exc.__class__.__name__}"
                if attempt >= attempts - 1:
                    return SendResult(self.channel, "failed", last_error)
                self._sleep_before_retry(attempt)
                continue
            if response.status_code not in self.retryable_statuses or attempt >= attempts - 1:
                break
            self._sleep_before_retry(attempt, response)
        if response is None:
            return SendResult(self.channel, "failed", last_error or "request_failed")
        if response.status_code in ok_statuses:
            api_error = self._api_error(response)
            if api_error:
                return SendResult(self.channel, "failed", api_error)
            return SendResult(self.channel, "sent", message_id=self._message_id(response))
        retryable = "retryable" if response.status_code in self.retryable_statuses else "http_error"
        return SendResult(self.channel, "failed", f"{retryable}:{response.status_code}")

    def _verify(self) -> bool | str:
        value = self.config.get("verify", True)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"0", "false", "no", "off"}:
                return False
            return value
        return bool(value)

    def _proxies(self) -> dict[str, str] | None:
        value = self.config.get("proxies")
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        proxy = self._value("proxy")
        if proxy:
            return {"http": proxy, "https": proxy}
        return None

    def _sleep_before_retry(self, attempt: int, response: requests.Response | None = None) -> None:
        retry_after = ""
        if response is not None:
            retry_after = str(response.headers.get("Retry-After") or "").strip()
        try:
            delay = float(retry_after) if retry_after else min(2.0, 0.25 * (2 ** attempt))
        except ValueError:
            delay = min(2.0, 0.25 * (2 ** attempt))
        if delay > 0:
            time.sleep(delay)

    def _api_error(self, response: requests.Response) -> str:
        return ""

    def _message_id(self, response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        if not isinstance(data, dict):
            return ""
        result = data.get("result")
        if isinstance(result, dict):
            return str(result.get("message_id") or result.get("id") or "")
        data_obj = data.get("data")
        if isinstance(data_obj, dict):
            return str(data_obj.get("message_id") or data_obj.get("id") or "")
        messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            return str(messages[0].get("id") or "")
        return str(data.get("id") or "")
