from __future__ import annotations

import platform
import threading


def request_macos_microphone_permission(timeout: float = 20.0) -> tuple[bool, str]:
    """Request macOS microphone permission through AVFoundation when available."""
    if platform.system() != "Darwin":
        return True, ""

    try:
        import AVFoundation  # type: ignore
    except Exception as exc:
        return (
            False,
            "缺少 macOS 麦克风授权组件 pyobjc-framework-AVFoundation，无法主动弹出系统权限请求。",
        )

    media_type = getattr(AVFoundation, "AVMediaTypeAudio", "soun")
    status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(media_type)

    # AVAuthorizationStatusAuthorized == 3
    if int(status) == 3:
        return True, ""
    # AVAuthorizationStatusDenied == 2, Restricted == 1
    if int(status) in (1, 2):
        return False, "麦克风权限已被系统拒绝，请到 系统设置 > 隐私与安全性 > 麦克风 中允许当前启动应用。"

    done = threading.Event()
    result = {"granted": False}

    def _completion(granted: bool) -> None:
        result["granted"] = bool(granted)
        done.set()

    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        media_type,
        _completion,
    )
    done.wait(timeout)
    if result["granted"]:
        return True, ""
    return False, "未获得麦克风权限，请在系统弹窗中允许，或到系统设置里开启麦克风权限。"
