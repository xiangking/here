from __future__ import annotations

from core.sprite.emotion_tags import filter_emotion_tags


def test_filter_emotion_tags_keeps_only_existing_sprite_ids():
    text = "\n".join(
        [
            "核心情绪标准名：neutral/happy/thinking",
            "",
            "立绘 1：neutral",
            "立绘 2：happy",
            "立绘 3：thinking",
            "sprite 04：sad",
        ]
    )

    filtered = filter_emotion_tags(text, available_sprites=2)

    assert "核心情绪标准名" in filtered
    assert "立绘 1：neutral" in filtered
    assert "立绘 2：happy" in filtered
    assert "立绘 3" not in filtered
    assert "sprite 04" not in filtered


def test_filter_emotion_tags_without_sprites_removes_numbered_entries():
    filtered = filter_emotion_tags(
        "核心情绪标准名：neutral/happy\n立绘 1：neutral",
        available_sprites=0,
    )

    assert filtered == "核心情绪标准名：neutral/happy"
