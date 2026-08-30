from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.life import DEFAULT_TIMEZONE


@dataclass
class ContactPlanItem:
    id: str
    window_start: str
    window_end: str
    source_block_id: str = ""
    type: str = "share_moment"
    intent: str = ""
    memory_basis: list[str] = field(default_factory=list)
    message_seed: str = ""
    priority: str = "medium"
    cooldown_hours: float = 4.0
    skip_if_recent_user_message_minutes: int = 45
    requires_user_available: bool = False
    status: str = "pending"
    sent_at: str | None = None
    skipped_reason: str | None = None
    delivery_channel: str = ""
    delivery_status: str = ""
    delivery_reason: str = ""
    delivery_attempted_at: str | None = None
    photo_intent: str = ""
    photo_path: str = ""
    photo_status: str = ""
    photo_reason: str = ""
    user_replied: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContactPlanItem":
        return cls(
            id=str(data.get("id") or ""),
            window_start=str(data.get("window_start") or "09:00"),
            window_end=str(data.get("window_end") or "10:00"),
            source_block_id=str(data.get("source_block_id") or ""),
            type=str(data.get("type") or "share_moment"),
            intent=str(data.get("intent") or ""),
            memory_basis=[str(v).strip() for v in data.get("memory_basis", []) if str(v).strip()],
            message_seed=str(data.get("message_seed") or ""),
            priority=str(data.get("priority") or "medium"),
            cooldown_hours=float(data.get("cooldown_hours") or 4.0),
            skip_if_recent_user_message_minutes=int(data.get("skip_if_recent_user_message_minutes") or 45),
            requires_user_available=bool(data.get("requires_user_available") or False),
            status=str(data.get("status") or "pending"),
            sent_at=data.get("sent_at"),
            skipped_reason=data.get("skipped_reason"),
            delivery_channel=str(data.get("delivery_channel") or ""),
            delivery_status=str(data.get("delivery_status") or ""),
            delivery_reason=str(data.get("delivery_reason") or ""),
            delivery_attempted_at=data.get("delivery_attempted_at"),
            photo_intent=str(data.get("photo_intent") or ""),
            photo_path=str(data.get("photo_path") or ""),
            photo_status=str(data.get("photo_status") or ""),
            photo_reason=str(data.get("photo_reason") or ""),
            user_replied=data.get("user_replied"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "source_block_id": self.source_block_id,
            "type": self.type,
            "intent": self.intent,
            "memory_basis": list(self.memory_basis),
            "message_seed": self.message_seed,
            "priority": self.priority,
            "cooldown_hours": self.cooldown_hours,
            "skip_if_recent_user_message_minutes": self.skip_if_recent_user_message_minutes,
            "requires_user_available": self.requires_user_available,
            "status": self.status,
            "sent_at": self.sent_at,
            "skipped_reason": self.skipped_reason,
            "delivery_channel": self.delivery_channel,
            "delivery_status": self.delivery_status,
            "delivery_reason": self.delivery_reason,
            "delivery_attempted_at": self.delivery_attempted_at,
            "photo_intent": self.photo_intent,
            "photo_path": self.photo_path,
            "photo_status": self.photo_status,
            "photo_reason": self.photo_reason,
            "user_replied": self.user_replied,
        }


@dataclass
class DailyContactPlan:
    date: str
    timezone: str = DEFAULT_TIMEZONE
    daily_contact_limit: int = 2
    contact_style: str = "温柔、克制，不连续打扰。"
    contacts: list[ContactPlanItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyContactPlan":
        return cls(
            date=str(data.get("date") or ""),
            timezone=str(data.get("timezone") or DEFAULT_TIMEZONE),
            daily_contact_limit=int(data.get("daily_contact_limit") or 2),
            contact_style=str(data.get("contact_style") or "温柔、克制，不连续打扰。"),
            contacts=[
                ContactPlanItem.from_dict(item)
                for item in data.get("contacts", [])
                if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "timezone": self.timezone,
            "daily_contact_limit": self.daily_contact_limit,
            "contact_style": self.contact_style,
            "contacts": [item.to_dict() for item in self.contacts],
        }
