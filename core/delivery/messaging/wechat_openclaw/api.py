from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.delivery.messaging.wechat_openclaw.models import (
    DEFAULT_CDN_BASE_URL,
    DEFAULT_BASE_URL,
    DEFAULT_BOT_TYPE,
    LoginPollResult,
    LoginStartResult,
    WeChatAccount,
    WeChatInboundMessage,
)


GET_QRCODE_TIMEOUT = 5
QR_POLL_TIMEOUT = 35
API_TIMEOUT = 15
UPLOAD_TIMEOUT = 60
MEDIA_TYPES = {
    "image": 1,
    "video": 2,
    "file": 3,
    "voice": 4,
}


def start_login(*, base_url: str = DEFAULT_BASE_URL, bot_type: str = DEFAULT_BOT_TYPE) -> LoginStartResult:
    url = _url(base_url, f"ilink/bot/get_bot_qrcode?bot_type={quote(bot_type)}")
    response = requests.get(url, timeout=GET_QRCODE_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    qrcode = str(data.get("qrcode") or "")
    qrcode_url = str(data.get("qrcode_img_content") or "")
    if not qrcode or not qrcode_url:
        raise RuntimeError("wechat_login_qrcode_missing")
    return LoginStartResult(
        session_key=str(uuid.uuid4()),
        qrcode=qrcode,
        qrcode_url=qrcode_url,
        message="使用微信扫描二维码并在手机上确认登录。",
    )


def poll_login(
    *,
    qrcode: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = QR_POLL_TIMEOUT,
) -> LoginPollResult:
    url = _url(base_url, f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}")
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return LoginPollResult(status="wait", message="network_wait")
    status = str(data.get("status") or "wait")
    if status == "scaned_but_redirect":
        redirect_host = str(data.get("redirect_host") or "").strip()
        return LoginPollResult(
            status=status,
            redirect_base_url=f"https://{redirect_host}" if redirect_host else "",
            message="redirect",
        )
    if status == "confirmed":
        account_id = str(data.get("ilink_bot_id") or "").strip()
        token = str(data.get("bot_token") or "").strip()
        if not account_id or not token:
            return LoginPollResult(status="failed", message="wechat_login_missing_account_or_token")
        return LoginPollResult(
            status="confirmed",
            account=WeChatAccount(
                account_id=account_id,
                token=token,
                base_url=str(data.get("baseurl") or base_url or DEFAULT_BASE_URL),
                user_id=str(data.get("ilink_user_id") or ""),
            ),
            message="wechat_login_confirmed",
        )
    return LoginPollResult(status=status, message=status)


def get_updates(*, account: WeChatAccount, get_updates_buf: str, timeout: float = 35) -> dict:
    body = {
        "get_updates_buf": get_updates_buf or "",
        "base_info": _base_info(),
    }
    response = _post(
        account,
        "ilink/bot/getupdates",
        body,
        timeout=timeout,
    )
    return response


def send_text(*, account: WeChatAccount, to_user_id: str, text: str, context_token: str) -> str:
    client_id = f"here-wechat-{uuid.uuid4().hex}"
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {
                    "type": 1,
                    "text_item": {"text": text},
                }
            ],
            "context_token": context_token,
        },
        "base_info": _base_info(),
    }
    _post(account, "ilink/bot/sendmessage", body, timeout=API_TIMEOUT)
    return client_id


def send_image(*, account: WeChatAccount, to_user_id: str, image_path: str, context_token: str, caption: str = "") -> str:
    uploaded = upload_media(account=account, to_user_id=to_user_id, path=image_path, media_type="image")
    item = {
        "type": 2,
        "image_item": {
            "media": _media_payload(uploaded),
            "mid_size": uploaded.size,
        },
    }
    return _send_items(account=account, to_user_id=to_user_id, items=[item], context_token=context_token, caption=caption)


def send_file(*, account: WeChatAccount, to_user_id: str, file_path: str, context_token: str, caption: str = "") -> str:
    uploaded = upload_media(account=account, to_user_id=to_user_id, path=file_path, media_type="file")
    item = {
        "type": 4,
        "file_item": {
            "file_name": uploaded.name,
            "md5": uploaded.raw_md5,
            "len": str(uploaded.size),
            "media": _media_payload(uploaded),
        },
    }
    return _send_items(account=account, to_user_id=to_user_id, items=[item], context_token=context_token, caption=caption)


def upload_media(*, account: WeChatAccount, path: str, media_type: str, to_user_id: str = "") -> "UploadedMedia":
    source = Path(path).expanduser()
    raw = source.read_bytes()
    aes_key = os.urandom(16)
    aes_key_hex = aes_key.hex()
    file_key = os.urandom(16).hex()
    encrypted = _aes_ecb_encrypt(raw, aes_key)
    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    upload_info = _get_upload_url(
        account=account,
        to_user_id=to_user_id,
        file_key=file_key,
        raw_size=len(raw),
        raw_md5=hashlib.md5(raw).hexdigest(),
        encrypted_size=len(encrypted),
        aes_key_hex=aes_key_hex,
        media_type=media_type,
    )
    upload_param = _first_value(upload_info, "upload_param")
    upload_url = _first_value(upload_info, "upload_full_url", "upload_url", "url", "uploadurl")
    if not upload_url and upload_param:
        upload_url = f"{DEFAULT_CDN_BASE_URL}/upload?encrypted_query_param={quote(upload_param)}&filekey={quote(file_key)}"
    if not upload_url:
        raise RuntimeError("wechat_upload_url_missing")
    headers = _upload_headers(upload_info, mime_type)
    response = requests.post(upload_url, data=encrypted, headers=headers, timeout=UPLOAD_TIMEOUT)
    response.raise_for_status()
    encrypted_param = str(
        response.headers.get("x-encrypted-param")
        or response.headers.get("X-Encrypted-Param")
        or upload_param
        or ""
    )
    return UploadedMedia(
        name=source.name,
        size=len(raw),
        encrypted_size=len(encrypted),
        mime_type=mime_type,
        aes_key=base64.b64encode(aes_key_hex.encode("ascii")).decode("ascii"),
        raw_md5=hashlib.md5(raw).hexdigest(),
        encrypted_param=encrypted_param,
        file_key=file_key,
        raw=upload_info,
    )


def parse_inbound_messages(data: dict) -> list[WeChatInboundMessage]:
    out: list[WeChatInboundMessage] = []
    for item in data.get("msgs") or []:
        if not isinstance(item, dict):
            continue
        from_user_id = str(item.get("from_user_id") or "")
        if not from_user_id:
            continue
        items = item.get("item_list")
        text = _text_from_items(items)
        out.append(
            WeChatInboundMessage(
                from_user_id=from_user_id,
                to_user_id=str(item.get("to_user_id") or ""),
                context_token=str(item.get("context_token") or ""),
                text=text,
                message_id=str(item.get("message_id") or item.get("client_id") or ""),
                item_types=_item_types(items),
            )
        )
    return out


class UploadedMedia:
    def __init__(
        self,
        *,
        name: str,
        size: int,
        encrypted_size: int,
        mime_type: str,
        aes_key: str,
        raw_md5: str = "",
        encrypted_param: str = "",
        file_key: str,
        raw: dict,
    ) -> None:
        self.name = name
        self.size = size
        self.encrypted_size = encrypted_size
        self.mime_type = mime_type
        self.aes_key = aes_key
        self.raw_md5 = raw_md5
        self.encrypted_param = encrypted_param
        self.file_key = file_key
        self.raw = raw


def _post(account: WeChatAccount, endpoint: str, body: dict, *, timeout: float) -> dict:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {account.token}",
        "Content-Length": str(len(raw.encode("utf-8"))),
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": "",
        "iLink-App-ClientVersion": "0",
    }
    response = requests.post(
        _url(account.base_url, endpoint),
        headers=headers,
        data=raw.encode("utf-8"),
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.text.strip():
        return {}
    data = response.json()
    if isinstance(data, dict):
        code = data.get("ret", data.get("errcode", 0))
        try:
            bad = int(code or 0) != 0
        except (TypeError, ValueError):
            bad = False
        if bad:
            raise RuntimeError(f"wechat_openclaw_error:{code}")
    return data if isinstance(data, dict) else {}


def _send_items(
    *,
    account: WeChatAccount,
    to_user_id: str,
    items: list[dict],
    context_token: str,
    caption: str = "",
    message_type: int = 2,
) -> str:
    client_id = f"here-wechat-{uuid.uuid4().hex}"
    item_list = list(items)
    caption = caption.strip()
    if caption:
        item_list.insert(0, {"type": 1, "text_item": {"text": caption}})
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": int(message_type),
            "message_state": 2,
            "item_list": item_list,
            "context_token": context_token,
        },
        "base_info": _base_info(),
    }
    _post(account, "ilink/bot/sendmessage", body, timeout=API_TIMEOUT)
    return client_id


def _media_payload(uploaded: UploadedMedia) -> dict:
    return {
        "encrypt_type": 1,
        "aes_key": uploaded.aes_key,
        "encrypt_query_param": uploaded.encrypted_param,
    }


def _get_upload_url(
    *,
    account: WeChatAccount,
    to_user_id: str,
    file_key: str,
    raw_size: int,
    raw_md5: str,
    encrypted_size: int,
    aes_key_hex: str,
    media_type: str,
) -> dict:
    body = {
        "filekey": file_key,
        "media_type": MEDIA_TYPES.get(media_type, 3),
        "to_user_id": to_user_id,
        "rawsize": raw_size,
        "rawfilemd5": raw_md5,
        "filesize": encrypted_size,
        "no_need_thumb": True,
        "aeskey": aes_key_hex,
        "base_info": _base_info(),
    }
    return _post(account, "ilink/bot/getuploadurl", body, timeout=API_TIMEOUT)


def _upload_headers(upload_info: dict, mime_type: str) -> dict[str, str]:
    headers = {"Content-Type": mime_type}
    raw_headers = upload_info.get("headers") or upload_info.get("upload_headers")
    if isinstance(raw_headers, dict):
        headers.update({str(key): str(value) for key, value in raw_headers.items()})
    return headers


def _first_value(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    nested = data.get("data")
    if isinstance(nested, dict):
        return _first_value(nested, *keys)
    return ""


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    padded = data + bytes([pad]) * pad
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _text_from_items(items) -> str:
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == 1:
            text_item = item.get("text_item")
            if isinstance(text_item, dict):
                return str(text_item.get("text") or "")
        if item.get("type") == 3:
            voice_item = item.get("voice_item")
            if isinstance(voice_item, dict) and voice_item.get("text"):
                return str(voice_item.get("text") or "")
    return ""


def _item_types(items) -> tuple[int, ...]:
    if not isinstance(items, list):
        return ()
    types: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            types.append(int(item.get("type")))
        except (TypeError, ValueError):
            continue
    return tuple(types)


def _base_info() -> dict:
    return {"channel_version": "here"}


def _random_wechat_uin() -> str:
    return base64.b64encode(str(int.from_bytes(os.urandom(4), "big")).encode("utf-8")).decode("ascii")


def _url(base_url: str, endpoint: str) -> str:
    base = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/"
    return urljoin(base, endpoint)
