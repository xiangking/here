from __future__ import annotations

from app.desktop import bootstrap


def test_try_init_audio_mixer_returns_false_when_unavailable(monkeypatch) -> None:
    messages: list[str] = []

    def fail_init() -> None:
        raise RuntimeError("no audio device")

    monkeypatch.setattr(bootstrap.pygame.mixer, "init", fail_init)
    monkeypatch.setattr(bootstrap.traceback, "print_exc", lambda: None)

    ok = bootstrap._try_init_audio_mixer(
        lambda key, **kwargs: messages.append(f"{key}:{kwargs['e']}") or "audio unavailable"
    )

    assert ok is False
    assert messages == ["main.print_audio_unavailable:no audio device"]


def test_try_init_audio_mixer_returns_true_when_available(monkeypatch) -> None:
    called = False

    def init() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(bootstrap.pygame.mixer, "init", init)

    assert bootstrap._try_init_audio_mixer(lambda key, **kwargs: key) is True
    assert called is True
