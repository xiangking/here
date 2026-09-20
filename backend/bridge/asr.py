from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    Path,
    default_vosk_model_path,
    importlib,
    is_vosk_model_dir,
    normalize_asr_provider_storage_key,
    shutil,
    subprocess,
    sys,
    urllib,
    zipfile,
)


def start_asr(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # Electron owns the user-facing macOS permission request. A Python
    # child process may have a different TCC identity, so do not repeat
    # the check when the host has already authorized this request.
    host_authorized = isinstance(payload, dict) and payload.get("__here_macos_microphone_authorized") is True
    if not host_authorized:
        permission_granted, permission_message = hooks.request_macos_microphone_permission()
        if not permission_granted:
            raise RuntimeError(permission_message)
    if self.asr_adapter is None:
        self.asr_adapter = hooks.create_default_asr_adapter(
            lambda text, is_partial: hooks.event(
                "transcript",
                {"text": text, "final": not bool(is_partial)},
            )
        )
    self.asr_adapter.start()
    status = self.asr_adapter.get_status()
    hooks.event("asr_state", {"running": status == "Running", "paused": False})
    return {"status": status}


def stop_asr(self) -> dict[str, Any]:
    if self.asr_adapter is not None:
        self.asr_adapter.stop()
    hooks.event("asr_state", {"running": False, "paused": False})
    return {"status": "Stopped"}


def pause_asr(self) -> dict[str, Any]:
    if self.asr_adapter is not None:
        self.asr_adapter.pause()
    running = self.asr_adapter is not None and self.asr_adapter.get_status() == "Running"
    return {"status": "Paused" if running else "Stopped"}


def resume_asr(self) -> dict[str, Any]:
    if self.asr_adapter is not None:
        self.asr_adapter.resume()
    return {"status": self.asr_adapter.get_status() if self.asr_adapter else "Stopped"}


def _configured_vosk_model_path(self, payload: dict[str, Any] | None = None) -> str:
    """Resolve the Vosk directory from an explicit form value or saved settings."""
    requested = str((payload or {}).get("model_path") or "").strip()
    if requested:
        return requested
    extra = self.config.config.api_config.asr_extra_configs or {}
    vosk_config = extra.get("vosk") or {}
    configured = vosk_config.get("model_path") if isinstance(vosk_config, dict) else ""
    return str(configured or "").strip() or default_vosk_model_path()


def _download_vosk_model(self, model_path: str) -> str:
    """Download and unpack the bundled small Chinese Vosk model on demand."""
    target = Path(model_path).expanduser()
    if is_vosk_model_dir(target):
        return target.as_posix()
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f".{target.name}.download.zip"
    url = "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
    hooks.event("status", {"text": "正在下载 Vosk 模型…", "busy": True})
    try:
        urllib.request.urlretrieve(url, archive)
        hooks.event("status", {"text": "正在解压 Vosk 模型…", "busy": True})
        with zipfile.ZipFile(archive) as zf:
            root = target.parent.resolve()
            for member in zf.infolist():
                destination = (root / member.filename).resolve()
                if destination != root and root not in destination.parents:
                    raise RuntimeError("Vosk 模型压缩包包含非法路径。")
            zf.extractall(root)
        extracted = target.parent / "vosk-model-small-cn-0.22"
        if target.resolve() != extracted.resolve():
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if extracted.is_dir():
                shutil.move(extracted.as_posix(), target.as_posix())
        if not is_vosk_model_dir(target):
            raise RuntimeError(f"Vosk 模型解压后目录无效：{target}")
        return target.as_posix()
    finally:
        try:
            archive.unlink()
        except OSError:
            pass
        hooks.event("status", {"text": "", "busy": False})


def prepare_asr(self, payload: dict[str, Any]) -> dict[str, Any]:
    provider = normalize_asr_provider_storage_key(str(payload.get("provider") or "vosk"))
    missing = hooks.missing_asr_requirements(provider)
    if missing:
        raise RuntimeError("缺少 ASR 依赖：" + "、".join(missing))
    if provider == "vosk":
        model_path = self._configured_vosk_model_path(payload)
        status = hooks.build_asr_setup_status(provider, model_path=model_path)
        if status.needs_model:
            model_path = self._download_vosk_model(model_path)
            status = hooks.build_asr_setup_status(provider, model_path=model_path)
        if not status.ready:
            raise RuntimeError(status.user_message())
        return {"provider": provider, "ready": True, "model": model_path}
    model = str(payload.get("model") or "small").strip() or "small"
    if provider == "faster_whisper":
        from faster_whisper import WhisperModel

        device = str(payload.get("device") or "auto")
        compute_type = str(payload.get("compute_type") or "").strip() or "default"
        WhisperModel(model, device=device, compute_type=compute_type)
    return {"provider": provider, "ready": True, "model": model}


def dependency_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "asr": {
            provider: {
                "missing": hooks.missing_asr_requirements(provider),
                "ready": hooks.build_asr_setup_status(
                    provider,
                    model_path=self._configured_vosk_model_path(payload) if provider == "vosk" else None,
                ).ready,
            }
            for provider in ("vosk", "faster_whisper", "realtime_stt")
        },
        "video": {"missing": [] if importlib.util.find_spec("cv2") else ["cv2"]},
        "hermes": {
            "missing": []
            if importlib.util.find_spec("run_agent") and importlib.util.find_spec("hermes_cli.config")
            else ["hermes-agent"]
        },
    }


def install_dependencies(self, payload: dict[str, Any]) -> dict[str, Any]:
    feature = str(payload.get("feature") or "").strip().lower().replace("-", "_")
    packages = {
        "vosk": ("pyaudio", "vosk==0.3.44"),
        "faster_whisper": ("pyaudio", "faster-whisper"),
        "realtime_stt": ("RealtimeSTT",),
        "video": ("opencv-python",),
        "hermes": ("git+https://github.com/NousResearch/hermes-agent.git@0f0e20ef81709a6dd590b25af380b116db67628c",),
    }.get(feature)
    if not packages:
        raise ValueError(f"不支持的依赖功能：{feature}")
    target = self.paths.python_packages_dir
    target.mkdir(parents=True, exist_ok=True)
    hooks.event("status", {"text": f"正在安装 {feature} 依赖…", "busy": True})
    command = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(target), *packages]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30 * 60)
    if completed.returncode != 0:
        tail = "\n".join(completed.stdout.splitlines()[-12:])
        raise RuntimeError(f"依赖安装失败：\n{tail}")
    importlib.invalidate_caches()
    hooks.event("status", {"text": f"{feature} 依赖安装完成。", "busy": False})
    return self.dependency_status()
