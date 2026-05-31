from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from ui.desktop import asr_settings_dialog as dialog_mod
from ui.desktop.asr_settings_dialog import ASRSettingsDialog


class _ConfigManagerStub:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            system_config=SimpleNamespace(
                asr_provider="faster_whisper",
                asr_language="",
                asr_whisper_model_size="small",
                asr_whisper_device="auto",
                asr_whisper_compute_type="",
            )
        )

    def get_adapter_extra_config(self, *_args) -> dict:
        return {}

    def set_adapter_extra_config(self, *_args) -> None:
        pass

    def save_system_config(self) -> None:
        pass

    def save_api_config(self) -> None:
        pass


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_packaged_asr_install_targets_user_package_dir(tmp_path, monkeypatch):
    _app()
    app_home = tmp_path / "home"
    runtime_python = tmp_path / "bundle" / "runtime" / "bin" / "python3"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_python.chmod(0o755)
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    monkeypatch.setattr(dialog_mod.sys, "executable", str(runtime_python))

    dialog = ASRSettingsDialog(config_manager=_ConfigManagerStub())
    command, cwd, env = dialog._dependency_install_command("faster_whisper")

    py_tag = f"py{sys.version_info.major}.{sys.version_info.minor}"
    target = app_home / "cache" / "python-packages" / py_tag
    assert command[:4] == [str(runtime_python), "-m", "pip", "install"]
    assert "--target" in command
    assert str(target) in command
    assert cwd is None
    assert env is not None
    assert str(target) in env["PYTHONPATH"]


def test_source_asr_install_uses_uv_sync(monkeypatch):
    _app()
    dialog = ASRSettingsDialog(config_manager=_ConfigManagerStub())
    monkeypatch.setattr(dialog, "_can_install_dependencies", lambda: True)
    monkeypatch.setattr(dialog, "_project_root", lambda: Path("/tmp/here-source"))
    monkeypatch.setattr(dialog_mod.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    command, cwd, _env = dialog._dependency_install_command("faster_whisper")

    assert command == ["/usr/bin/uv", "sync", "--python", "3.11", "--extra", "asr"]
    assert cwd == Path("/tmp/here-source")


def test_packaged_vosk_install_targets_user_package_dir(tmp_path, monkeypatch):
    _app()
    app_home = tmp_path / "home"
    runtime_python = tmp_path / "bundle" / "runtime" / "bin" / "python3"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_python.chmod(0o755)
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    monkeypatch.setattr(dialog_mod.sys, "executable", str(runtime_python))

    dialog = ASRSettingsDialog(config_manager=_ConfigManagerStub())
    command, cwd, env = dialog._dependency_install_command("vosk")

    py_tag = f"py{sys.version_info.major}.{sys.version_info.minor}"
    target = app_home / "cache" / "python-packages" / py_tag
    assert command[:4] == [str(runtime_python), "-m", "pip", "install"]
    assert "pyaudio" in command
    assert "vosk" in command
    assert "--target" in command
    assert str(target) in command
    assert cwd is None
    assert env is not None
    assert str(target) in env["PYTHONPATH"]
