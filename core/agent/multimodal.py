from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Any


IMAGE_REF_RE = re.compile(r"\[图片:\s*(?P<path>[^\]\n]+?)\s*\]")


def extract_image_paths(text: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for match in IMAGE_REF_RE.finditer(str(text or "")):
        raw = match.group("path").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def strip_image_refs(text: str) -> str:
    return IMAGE_REF_RE.sub("", str(text or "")).strip()


def image_path_to_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.as_posix())[0] or "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def build_hermes_user_message(text: str) -> str | list[dict[str, Any]]:
    """Convert `[图片: path]` markers into OpenAI-style multimodal content parts.

    Hermes already owns model/provider handling. Here only packages local user
    attachments so Hermes can see the images natively.
    """

    raw_text = str(text or "")
    image_paths = [path for path in extract_image_paths(raw_text) if path.is_file()]
    if not image_paths:
        return raw_text

    clean_text = strip_image_refs(raw_text) or "请看这张图片。"
    content: list[dict[str, Any]] = [{"type": "text", "text": clean_text}]
    for path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_path_to_data_uri(path)},
            }
        )
    return content
