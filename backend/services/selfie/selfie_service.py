from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from infrastructure.paths import get_app_paths, resolve_character_asset_path


@dataclass(frozen=True)
class SelfieRequest:
    character: Any
    life_state: str
    photo_intent: str
    contact_text: str = ""
    emotion: str = "neutral"
    now: datetime | None = None


@dataclass(frozen=True)
class SelfieResult:
    path: str
    prompt: str
    provider: str


class SelfieService:
    """Generate an optional photo attachment for proactive contact.

    The proactive-contact flow owns when a photo is useful. This service only
    turns that contact context into a provider-neutral image prompt and calls
    the currently configured T2I manager.
    """

    def __init__(
        self,
        *,
        t2i_manager: Any,
        provider_name: str = "",
        output_dir: str | Path | None = None,
        default_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.t2i_manager = t2i_manager
        self.provider_name = str(provider_name or "").strip()
        self.output_dir = Path(output_dir) if output_dir is not None else get_app_paths().selfies_dir
        self.default_kwargs = dict(default_kwargs or {})
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, request: SelfieRequest) -> SelfieResult | None:
        if self.t2i_manager is None:
            return None
        prompt = self.build_prompt(request)
        if not prompt:
            return None
        file_path = self.output_dir / self._filename(request)
        kwargs = dict(self.default_kwargs)
        reference_image = str(getattr(request.character, "visual_reference_image", "") or "").strip()
        if reference_image:
            kwargs.setdefault("reference_image_path", _resolve_reference_image(reference_image))
        if not kwargs.get("size"):
            kwargs.setdefault("width", 1024)
            kwargs.setdefault("height", 1024)
        kwargs.setdefault(
            "negative_prompt",
            "low quality, blurry, distorted face, extra fingers, text, watermark, logo",
        )
        try:
            path = self.t2i_manager.t2i(prompt, file_path=file_path.as_posix(), **kwargs)
        except TypeError:
            # Older or mocked managers may not accept file_path. Keep the service
            # usable in tests and when adapters lag behind the richer contract.
            path = self.t2i_manager.t2i(prompt, **kwargs)
        if not path:
            return None
        return SelfieResult(path=str(path), prompt=prompt, provider=self.provider_name)

    def build_prompt(self, request: SelfieRequest) -> str:
        character = request.character
        name = str(getattr(character, "name", "") or "the character").strip()
        visual_identity = str(getattr(character, "visual_identity", "") or "").strip()
        reference_image = str(getattr(character, "visual_reference_image", "") or "").strip()
        style_bits = ["natural realistic daily photo", "keep the same character as the reference image"]
        if visual_identity and not reference_image:
            style_bits.append(_compact_text(visual_identity, 120))
        if request.emotion:
            style_bits.append(f"mood: {request.emotion}")
        lines = [
            ", ".join(style_bits),
            f"Subject: {name}.",
        ]
        lines.extend(
            [
                f"Current state: {_compact_text(request.life_state, 120)}",
                f"Photo intent: {_compact_text(request.photo_intent, 120)}",
            ]
        )
        if request.contact_text:
            lines.append(f"Message context: {_compact_text(request.contact_text, 60)}")
        lines.append(
            "Make it feel like a natural moment from her daily life. No chat UI, no visible phone, no character sheet, no illustration, no animal, no captions, no embedded text."
        )
        return "\n".join(line for line in lines if line.strip()).strip()

    def _filename(self, request: SelfieRequest) -> str:
        character_name = str(getattr(request.character, "name", "") or "character")
        slug = re.sub(r"[^0-9A-Za-z_-]+", "_", character_name).strip("_") or "character"
        stamp = (request.now or datetime.now()).strftime("%Y%m%d_%H%M%S")
        return f"{slug}_{stamp}.png"


def _compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "."


def _resolve_reference_image(value: str) -> str:
    text = str(value or "").strip()
    if text.lower().startswith(("http://", "https://", "data:")):
        return text
    return resolve_character_asset_path(text).as_posix()
