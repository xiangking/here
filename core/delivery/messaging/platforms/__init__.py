from core.delivery.messaging.platforms.desktop import DesktopMessagePlatform
from core.delivery.messaging.platforms.discord import DiscordMessagePlatform
from core.delivery.messaging.platforms.feishu import FeishuMessagePlatform
from core.delivery.messaging.platforms.telegram import TelegramMessagePlatform
from core.delivery.messaging.platforms.wechat import WeChatMessagePlatform
from core.delivery.messaging.platforms.whatsapp import WhatsAppMessagePlatform

__all__ = [
    "DesktopMessagePlatform",
    "DiscordMessagePlatform",
    "FeishuMessagePlatform",
    "TelegramMessagePlatform",
    "WeChatMessagePlatform",
    "WhatsAppMessagePlatform",
]
