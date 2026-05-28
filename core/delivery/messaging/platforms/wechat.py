from core.delivery.messaging.models import SendResult
from core.delivery.messaging.platforms.base import BaseMessagePlatform
from core.delivery.messaging.wechat_openclaw import api, state
from core.delivery.messaging.wechat_openclaw.models import DEFAULT_BASE_URL, WeChatAccount


class WeChatMessagePlatform(BaseMessagePlatform):
    channel = "wechat"
    label = "WeChat"
    target_fields = ("target", "recipient", "user_id")
    target_required = True

    def configured(self) -> tuple[bool, str]:
        account = self._account()
        if account is None:
            return False, "missing_wechat_login"
        if not self.default_target():
            return False, "missing_target"
        if self._require_context_token() and not state.get_context_token(account.account_id, self.default_target()):
            return False, "missing_context_token"
        return True, "ready"

    def send(self, *, target: str, text: str) -> SendResult:
        account, context_token, failed = self._session(target)
        if failed:
            return failed
        try:
            message_id = api.send_text(account=account, to_user_id=target, text=text, context_token=context_token)
        except Exception as exc:
            return SendResult(self.channel, "failed", f"wechat_openclaw_error:{exc.__class__.__name__}")
        return SendResult(self.channel, "sent", message_id=message_id)

    def send_image(self, *, target: str, image_path: str, caption: str = "") -> SendResult:
        account, context_token, failed = self._session(target)
        if failed:
            return failed
        try:
            message_id = api.send_image(
                account=account,
                to_user_id=target,
                image_path=image_path,
                context_token=context_token,
                caption=caption,
            )
        except FileNotFoundError:
            return SendResult(self.channel, "failed", "missing_image")
        except Exception as exc:
            return SendResult(self.channel, "failed", f"wechat_openclaw_error:{exc.__class__.__name__}")
        return SendResult(self.channel, "sent", message_id=message_id)

    def send_audio(self, *, target: str, audio_path: str, caption: str = "") -> SendResult:
        account, context_token, failed = self._session(target)
        if failed:
            return failed
        try:
            message_id = api.send_file(
                account=account,
                to_user_id=target,
                file_path=audio_path,
                context_token=context_token,
                caption=caption,
            )
        except FileNotFoundError:
            return SendResult(self.channel, "failed", "missing_audio")
        except Exception as exc:
            return SendResult(self.channel, "failed", f"wechat_openclaw_error:{exc.__class__.__name__}")
        return SendResult(self.channel, "sent", message_id=message_id)

    def _session(self, target: str) -> tuple[WeChatAccount | None, str, SendResult | None]:
        account = self._account()
        if account is None:
            return None, "", SendResult(self.channel, "failed", "missing_wechat_login")
        context_token = self._value("context_token") or state.get_context_token(account.account_id, target)
        if self._require_context_token() and not context_token:
            return account, "", SendResult(self.channel, "failed", "missing_context_token")
        return account, context_token, None

    def _account(self) -> WeChatAccount | None:
        account_id = self._value("account_id")
        token = self._value("token")
        if token:
            return WeChatAccount(
                account_id=account_id or "configured",
                token=token,
                base_url=self._value("base_url") or DEFAULT_BASE_URL,
                user_id=self._value("user_id"),
            )
        return state.load_account(account_id)

    def _require_context_token(self) -> bool:
        raw = str(self.config.get("require_context_token", True)).strip().lower()
        return raw not in {"0", "false", "no", "off"}
