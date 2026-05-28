from __future__ import annotations

from core.agent.multimodal import build_hermes_user_message, extract_image_paths


def test_extract_image_paths_deduplicates(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake")

    paths = extract_image_paths(f"看图 [图片: {image}] 再来 [图片: {image}]")

    assert paths == [image]


def test_build_hermes_user_message_uses_image_url_content_parts(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake image bytes")

    message = build_hermes_user_message(f"看看这个\n[图片: {image}]")

    assert isinstance(message, list)
    assert message[0] == {"type": "text", "text": "看看这个"}
    assert message[1]["type"] == "image_url"
    assert message[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_hermes_user_message_ignores_missing_images(tmp_path):
    missing = tmp_path / "missing.png"

    message = build_hermes_user_message(f"看看这个\n[图片: {missing}]")

    assert isinstance(message, str)
    assert "[图片:" in message
