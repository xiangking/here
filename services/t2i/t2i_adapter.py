from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from services.t2i.protocols import T2IAdapter


DEFAULT_FAL_BASE_URL = "https://fal.run"
DEFAULT_FAL_GROK_ENDPOINT = "xai/grok-imagine-image"
DEFAULT_FAL_GROK_EDIT_URL = f"{DEFAULT_FAL_BASE_URL}/{DEFAULT_FAL_GROK_ENDPOINT}/edit"
DEFAULT_OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_GROK_MODEL = "x-ai/grok-imagine-image-quality"
DEFAULT_OPENROUTER_GROK_MODEL_PAGE_URL = f"https://openrouter.ai/{DEFAULT_OPENROUTER_GROK_MODEL}/api"
LEGACY_XAI_GROK_MODELS = {"grok-imagine-image-quality", "grok-imagine-image"}
FAL_GROK_MODELS = {DEFAULT_FAL_GROK_ENDPOINT, *LEGACY_XAI_GROK_MODELS}


def _normalize_image_generation_url(api_url: str) -> str:
    url = str(api_url or "").strip().rstrip("/")
    if not url:
        return url
    if url.endswith("/images/generations"):
        return url
    if url.endswith("/v1"):
        return f"{url}/images/generations"
    return f"{url}/v1/images/generations"


def _normalize_image_edit_url(api_url: str) -> str:
    url = str(api_url or "").strip().rstrip("/")
    if not url:
        return url
    if url.endswith("/images/edits"):
        return url
    if url.endswith("/images/generations"):
        return f"{url[: -len('/images/generations')]}/images/edits"
    if url.endswith("/v1"):
        return f"{url}/images/edits"
    return f"{url}/v1/images/edits"


def _looks_like_fal_url(api_url: str) -> bool:
    parsed = urlparse(str(api_url or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return "fal.run" in host or not path.endswith("/v1/images/generations")


def _looks_like_openrouter_url(api_url: str) -> bool:
    parsed = urlparse(str(api_url or ""))
    host = parsed.netloc.lower()
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


def _normalize_openrouter_chat_url(api_url: str) -> str:
    raw = str(api_url or "").strip().rstrip("/")
    if not raw:
        return DEFAULT_OPENROUTER_CHAT_COMPLETIONS_URL
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    if _looks_like_openrouter_url(raw):
        if path.endswith("/api/v1/chat/completions"):
            return raw
        return DEFAULT_OPENROUTER_CHAT_COMPLETIONS_URL
    if raw.endswith("/chat/completions"):
        return raw
    if raw.endswith("/api/v1"):
        return f"{raw}/chat/completions"
    if raw.endswith("/v1"):
        return f"{raw}/chat/completions"
    return raw


def _openrouter_model_from_url(api_url: str) -> str:
    raw = str(api_url or "").strip()
    if not _looks_like_openrouter_url(raw):
        return ""
    parsed = urlparse(raw)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) >= 2 and parts[-1] == "api" and parts[0] != "api":
        return "/".join(parts[:-1])
    return ""


def _normalize_openrouter_model(default_model: Optional[str], api_url: str) -> str:
    url_model = _openrouter_model_from_url(api_url)
    model = str(default_model or "").strip()
    if model and model not in FAL_GROK_MODELS:
        return model
    if url_model:
        return url_model
    return DEFAULT_OPENROUTER_GROK_MODEL


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _file_to_data_url(path: str) -> str:
    source = Path(path).expanduser()
    mime_type = mimetypes.guess_type(source.name)[0] or "image/png"
    raw = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{raw}"


def _normalize_fal_proxy_url(api_url: str) -> str:
    return str(api_url or DEFAULT_FAL_BASE_URL).strip().rstrip("/") or DEFAULT_FAL_BASE_URL


def _split_fal_url(api_url: str, fallback_endpoint: str) -> tuple[str, str, str, str]:
    raw = str(api_url or "").strip().rstrip("/")
    if not raw:
        raw = DEFAULT_FAL_GROK_EDIT_URL
    parsed = urlparse(raw)
    path = parsed.path.strip("/")
    fallback = fallback_endpoint.strip("/")
    endpoint = fallback
    model_overrides_url = bool(fallback and fallback != DEFAULT_FAL_GROK_ENDPOINT)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else DEFAULT_FAL_BASE_URL
    if path:
        if path.endswith("/edit"):
            path_endpoint = path[: -len("/edit")].strip("/") or endpoint
            endpoint = endpoint if model_overrides_url else path_endpoint
        else:
            path_endpoint = path
            endpoint = endpoint if model_overrides_url else path_endpoint
        generation_url = f"{base_url}/{endpoint}"
        edit_url = f"{generation_url}/edit"
    else:
        generation_url = f"{base_url}/{endpoint}"
        edit_url = f"{generation_url}/edit"
    return base_url.rstrip("/"), endpoint, generation_url.rstrip("/"), edit_url.rstrip("/")


def _clean_fal_key(value: str) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("key "):
        return token[4:].strip()
    return token


def _image_value_to_bytes(value: Any) -> bytes | None:
    if isinstance(value, list):
        for item in value:
            image_data = _image_value_to_bytes(item)
            if image_data is not None:
                return image_data
        return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.startswith("data:") and "," in raw:
            try:
                return base64.b64decode(raw.split(",", 1)[1])
            except Exception:
                return None
        if _is_http_url(raw):
            resp = requests.get(raw, timeout=60)
            resp.raise_for_status()
            return resp.content
        try:
            return base64.b64decode(raw)
        except Exception:
            return None

    if isinstance(value, dict):
        for key in ("b64_json", "base64", "data", "image"):
            image_data = _image_value_to_bytes(value.get(key))
            if image_data is not None:
                return image_data
        for key in ("url", "image_url", "imageUrl"):
            image_data = _image_value_to_bytes(value.get(key))
            if image_data is not None:
                return image_data
    return None


class ImageAPIAdapter(T2IAdapter):
    """Generic text-to-image API adapter.

    The adapter posts a simple prompt payload and accepts common image API
    response shapes with base64 payloads or image URLs.
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:7860/v1/images/generations",
        default_model: Optional[str] = None,
        timeout_s: float = 120.0,
        api_format: str = "auto",
        **_ignored: Any,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.current_model = default_model
        self.timeout_s = float(timeout_s or 120.0)
        self.api_format = (api_format or "auto").strip().lower()

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_url": {
                "type": "str",
                "label": "生图 API 地址",
                "default": "http://127.0.0.1:7860/v1/images/generations",
            },
            "api_format": {
                "type": "select",
                "label": "请求格式",
                "default": "auto",
                "options": ["auto", "openai", "simple"],
            },
            "timeout_s": {
                "type": "float",
                "label": "请求超时（秒）",
                "default": 120.0,
                "min": 1.0,
                "max": 600.0,
                "step": 1.0,
            },
        }

    def _payload(self, prompt: str, **kwargs) -> dict[str, Any]:
        api_format = str(kwargs.get("api_format") or self.api_format or "auto").lower()
        if api_format == "auto":
            api_format = "openai" if "/images/generations" in self.api_url else "simple"

        if api_format == "openai":
            size = kwargs.get("size")
            if not size:
                width = int(kwargs.get("width", 1024) or 1024)
                height = int(kwargs.get("height", 1024) or 1024)
                size = f"{width}x{height}"
            payload = {
                "prompt": prompt,
                "n": int(kwargs.get("n", 1) or 1),
                "size": size,
            }
            if self.current_model:
                payload["model"] = self.current_model
            extra = kwargs.get("extra")
            if isinstance(extra, dict):
                payload.update(extra)
            return payload

        payload = {
            "prompt": prompt,
            "negative_prompt": kwargs.get("negative_prompt", "ugly, deformed, low quality"),
            "steps": int(kwargs.get("steps", 20) or 20),
            "width": int(kwargs.get("width", 1024) or 1024),
            "height": int(kwargs.get("height", 1024) or 1024),
            "sampler_name": kwargs.get("sampler_name", "Euler a"),
            "cfg_scale": float(kwargs.get("cfg_scale", 7) or 7),
            "seed": int(kwargs.get("seed", -1) or -1),
        }
        if self.current_model:
            payload["override_settings"] = {"sd_model_checkpoint": self.current_model}
        extra = kwargs.get("extra")
        if isinstance(extra, dict):
            payload.update(extra)
        return payload

    @staticmethod
    def _first_image_bytes(data: Any) -> bytes | None:
        if isinstance(data, dict):
            images = data.get("images")
            if isinstance(images, list) and images:
                image_data = _image_value_to_bytes(images[0])
                if image_data is not None:
                    return image_data
            for key in ("image", "url", "image_url"):
                image_data = _image_value_to_bytes(data.get(key))
                if image_data is not None:
                    return image_data
            data_block = data.get("data")
            if isinstance(data_block, list) and data_block:
                image_data = _image_value_to_bytes(data_block[0])
                if image_data is not None:
                    return image_data
            choices = data.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    for key in ("message", "delta"):
                        image_data = ImageAPIAdapter._first_image_bytes(choice.get(key))
                        if image_data is not None:
                            return image_data
                    image_data = ImageAPIAdapter._first_image_bytes(choice)
                    if image_data is not None:
                        return image_data
        return None

    def generate_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        payload = self._payload(prompt, **kwargs)
        try:
            response = requests.post(self.api_url, json=payload, timeout=self.timeout_s)
            response.raise_for_status()
            data = response.json()
            image_data = self._first_image_bytes(data)
            if image_data is None:
                print("Image API returned no usable image payload.")
                return None

            if not file_path:
                file_path = os.path.join(os.getcwd(), "temp_t2i.png")
            with open(file_path, "wb") as f:
                f.write(image_data)
            return os.path.abspath(file_path)
        except Exception as e:
            print(f"Image generation API failed: {e}")
            return None

    def switch_model(self, model_info: Dict[str, Any]) -> None:
        model = (
            model_info.get("model_checkpoint")
            or model_info.get("model")
            or model_info.get("checkpoint")
            or ""
        )
        if model and self.current_model != model:
            self.current_model = str(model)


class XAIGrokImagineAdapter(ImageAPIAdapter):
    """xAI image-generation adapter.

    This keeps xAI/Grok Imagine as one provider in the same T2I registry used by
    future image APIs. The request/response shape is OpenAI-compatible.
    """

    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        default_model: Optional[str] = DEFAULT_FAL_GROK_ENDPOINT,
        timeout_s: float = 300.0,
        api_style: str = "fal",
        fal_application: str = "",
        aspect_ratio: str = "1:1",
        image_size: str = "auto",
        output_format: str = "jpeg",
        **kwargs: Any,
    ) -> None:
        self.raw_api_url = str(api_url or "").strip()
        self.api_style = str(api_style or "fal").strip().lower()
        if _looks_like_openrouter_url(self.raw_api_url):
            self.api_style = "openrouter"
        self.aspect_ratio = str(aspect_ratio or "1:1").strip()
        self.image_size = str(image_size or "auto").strip()
        self.output_format = str(output_format or "jpeg").strip()
        endpoint = str(fal_application or default_model or DEFAULT_FAL_GROK_ENDPOINT).strip().strip("/")
        if endpoint in LEGACY_XAI_GROK_MODELS:
            endpoint = DEFAULT_FAL_GROK_ENDPOINT
        self.fal_proxy_url, endpoint, self.fal_generation_url, self.fal_edit_url = _split_fal_url(
            api_url,
            endpoint,
        )
        self.fal_application = endpoint
        effective_model = (
            _normalize_openrouter_model(default_model, self.raw_api_url)
            if self._use_openrouter_style(self.raw_api_url, self.api_style)
            else default_model
        )
        if self._use_openrouter_style(api_url, self.api_style):
            openai_api_url = _normalize_openrouter_chat_url(api_url)
        elif self._use_fal_style(api_url, self.api_style):
            openai_api_url = self.fal_edit_url
        else:
            openai_api_url = _normalize_image_generation_url(api_url)
        super().__init__(
            api_url=openai_api_url,
            default_model=effective_model,
            timeout_s=timeout_s,
            api_format="openai",
            **kwargs,
        )
        if api_key:
            resolved_api_key = api_key
        elif self._use_openrouter_style(self.raw_api_url, self.api_style):
            resolved_api_key = (
                os.environ.get("OPENROUTER_API_KEY", "")
                or os.environ.get("XAI_API_KEY", "")
                or os.environ.get("FAL_KEY", "")
            )
        else:
            resolved_api_key = (
                os.environ.get("FAL_KEY", "")
                or os.environ.get("XAI_API_KEY", "")
                or os.environ.get("OPENROUTER_API_KEY", "")
            )
        self.api_key = str(resolved_api_key or "").strip()

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_url": {
                "type": "str",
                "label": "Grok API URL",
                "default": DEFAULT_FAL_GROK_EDIT_URL,
            },
            "api_key": {
                "type": "password",
                "label": "fal/xAI/OpenRouter API Key",
                "default": "",
            },
            "api_style": {
                "type": "select",
                "label": "API style",
                "default": "fal",
                "choices": ["auto", "fal", "openrouter", "openai"],
            },
            "default_model": {
                "type": "str",
                "label": "Model",
                "default": DEFAULT_FAL_GROK_ENDPOINT,
            },
            "aspect_ratio": {
                "type": "select",
                "label": "Aspect ratio",
                "default": "1:1",
                "choices": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9", "2:1"],
            },
            "image_size": {
                "type": "select",
                "label": "Image size",
                "default": "auto",
                "choices": ["auto", "1K", "2K", "4K", "0.5K"],
            },
            "output_format": {
                "type": "select",
                "label": "Output format",
                "default": "jpeg",
                "choices": ["jpeg", "png", "webp"],
            },
            "timeout_s": {
                "type": "float",
                "label": "请求超时（秒）",
                "default": 300.0,
                "min": 1.0,
                "max": 600.0,
                "step": 1.0,
            },
        }

    @staticmethod
    def _use_fal_style(api_url: str, api_style: str) -> bool:
        style = str(api_style or "fal").strip().lower()
        if _looks_like_openrouter_url(api_url) or style == "openrouter":
            return False
        if style == "fal":
            return True
        if style == "openai":
            return False
        return _looks_like_fal_url(api_url)

    @staticmethod
    def _use_openrouter_style(api_url: str, api_style: str) -> bool:
        style = str(api_style or "fal").strip().lower()
        return style == "openrouter" or _looks_like_openrouter_url(api_url)

    def _openrouter_payload(self, prompt: str, **kwargs) -> dict[str, Any]:
        reference_image_path = str(kwargs.get("reference_image_path") or "").strip()
        content: str | list[dict[str, Any]]
        if reference_image_path:
            try:
                image_url = (
                    reference_image_path
                    if _is_http_url(reference_image_path) or reference_image_path.startswith("data:")
                    else _file_to_data_url(reference_image_path)
                )
            except Exception as exc:
                raise RuntimeError(f"cannot read reference image: {exc}") from exc
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        else:
            content = prompt
        raw_modalities = kwargs.get("modalities") or ["image"]
        modalities = [raw_modalities] if isinstance(raw_modalities, str) else list(raw_modalities)
        payload: dict[str, Any] = {
            "model": str(kwargs.get("model") or self.current_model or DEFAULT_OPENROUTER_GROK_MODEL),
            "messages": [{"role": "user", "content": content}],
            "modalities": modalities,
        }
        image_config = dict(kwargs.get("image_config") or {})
        aspect_ratio = str(kwargs.get("aspect_ratio") or self.aspect_ratio or "").strip()
        if aspect_ratio:
            image_config.setdefault("aspect_ratio", aspect_ratio)
        image_size = str(kwargs.get("image_size") or kwargs.get("size") or self.image_size or "").strip()
        if image_size and image_size.lower() != "auto":
            image_config.setdefault("image_size", image_size)
        if image_config:
            payload["image_config"] = image_config
        extra = kwargs.get("extra")
        if isinstance(extra, dict):
            payload.update(extra)
        return payload

    def generate_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        if not self.api_key:
            print("xAI image generation failed: missing FAL_KEY/XAI_API_KEY or api_key.")
            return None
        if self._use_openrouter_style(self.raw_api_url, self.api_style):
            return self._generate_openrouter_image(prompt, file_path=file_path, **kwargs)
        if self._use_fal_style(self.raw_api_url, self.api_style):
            return self._generate_fal_image(prompt, file_path=file_path, **kwargs)
        payload = self._payload(prompt, api_format="openai", **kwargs)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
            image_data = self._first_image_bytes(data)
            if image_data is None:
                print("xAI image API returned no usable image payload.")
                return None
            if not file_path:
                file_path = os.path.join(os.getcwd(), "temp_xai_image.png")
            with open(file_path, "wb") as f:
                f.write(image_data)
            return os.path.abspath(file_path)
        except Exception as e:
            print(f"xAI image generation failed: {e}")
            return None

    def _generate_openrouter_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        try:
            payload = self._openrouter_payload(prompt, **kwargs)
        except Exception as e:
            print(f"OpenRouter Grok Imagine generation failed: {e}")
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            if response.status_code >= 400:
                preview = response.text[:500].replace("\n", " ")
                raise RuntimeError(
                    f"openrouter_response_error status={response.status_code} url={self.api_url} body={preview}"
                )
            data = response.json()
            image_data = self._first_image_bytes(data)
            if image_data is None:
                print("OpenRouter Grok Imagine API returned no usable image payload.")
                return None
            if not file_path:
                file_path = os.path.join(os.getcwd(), "temp_openrouter_grok_image.png")
            with open(file_path, "wb") as f:
                f.write(image_data)
            return os.path.abspath(file_path)
        except Exception as e:
            print(f"OpenRouter Grok Imagine generation failed: {e}")
            return None

    def _generate_fal_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        reference_image_path = str(kwargs.get("reference_image_path") or "").strip()
        output_format = str(kwargs.get("output_format") or self.output_format or "jpeg").strip()
        body: dict[str, Any] = {
            "prompt": prompt,
            "num_images": int(kwargs.get("num_images", kwargs.get("n", 1)) or 1),
            "output_format": output_format,
        }
        url = self.fal_generation_url
        if reference_image_path:
            try:
                body["image_url"] = self._fal_reference_image_url(reference_image_path)
            except Exception as exc:
                print(f"xAI Grok Imagine edit failed: cannot read reference image: {exc}")
                return None
            url = self.fal_edit_url
        else:
            body["aspect_ratio"] = str(kwargs.get("aspect_ratio") or self.aspect_ratio or "1:1")
        token = f"Key {_clean_fal_key(self.api_key)}"
        headers = {"Authorization": token, "Content-Type": "application/json"}
        try:
            data = self._call_fal(body, url=url, headers=headers)
            image_data = self._first_image_bytes(data)
            if image_data is None:
                print("xAI Grok Imagine API returned no usable image payload.")
                return None
            if not file_path:
                file_path = os.path.join(os.getcwd(), f"temp_xai_image.{output_format}")
            with open(file_path, "wb") as f:
                f.write(image_data)
            return os.path.abspath(file_path)
        except Exception as e:
            print(f"xAI Grok Imagine generation failed: {e}")
            return None

    def _fal_reference_image_url(self, reference_image_path: str) -> str:
        if _is_http_url(reference_image_path):
            return reference_image_path
        image_path = Path(reference_image_path).expanduser()
        if not image_path.is_file():
            raise FileNotFoundError(reference_image_path)
        return self._upload_fal_reference_image(image_path)

    def _upload_fal_reference_image(self, image_path: Path) -> str:
        try:
            import fal_client
        except ImportError as exc:
            raise RuntimeError(
                "fal-client is required to upload local reference images for Grok Imagine edit."
            ) from exc
        client = fal_client.SyncClient(
            key=_clean_fal_key(self.api_key),
            default_timeout=self.timeout_s,
        )
        uploaded_url = str(client.upload_file(image_path))
        if not uploaded_url.strip():
            raise RuntimeError("fal upload returned an empty reference image URL.")
        return uploaded_url

    def _call_fal(self, body: dict[str, Any], *, url: str, headers: dict[str, str]) -> Any:
        return self._post_json(url, body, headers)

    def _uses_official_fal_client(self) -> bool:
        return urlparse(self.fal_proxy_url).netloc.lower() == "fal.run"

    def _fal_endpoint(self, *, is_edit: bool) -> str:
        endpoint = self.fal_application.strip("/")
        if is_edit and not endpoint.endswith("/edit"):
            endpoint = f"{endpoint}/edit"
        return endpoint

    def _post_json(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
        response = requests.post(url, json=body, headers=headers, timeout=self.timeout_s)
        if response.status_code >= 400:
            preview = response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"fal_response_error status={response.status_code} url={url} body={preview}"
            )
        try:
            return response.json()
        except ValueError as exc:
            preview = response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"non_json_response status={response.status_code} url={url} body={preview}"
            ) from exc


class OpenAIGPTImageAdapter(ImageAPIAdapter):
    """OpenAI GPT Image adapter using the Images API.

    The defaults mirror the GPT Image playground style: provider URL, API key,
    model, and image-generation mode are explicit config fields while the
    underlying request stays OpenAI-compatible.
    """

    def __init__(
        self,
        api_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        default_model: Optional[str] = "gpt-image-2",
        timeout_s: float = 600.0,
        size: str = "auto",
        quality: str = "auto",
        background: str = "auto",
        output_format: str = "png",
        output_compression: Optional[int] = None,
        moderation: str = "auto",
        stream_images: bool = False,
        stream_partial_images: int = 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_url=_normalize_image_generation_url(api_url),
            default_model=default_model,
            timeout_s=timeout_s,
            api_format="openai",
            **kwargs,
        )
        self.api_key = str(
            api_key
            or os.environ.get("OPENAI_API_KEY", "")
            or os.environ.get("SILICONFLOW_API_KEY", "")
            or os.environ.get("API_KEY", "")
            or ""
        ).strip()
        self.size = str(size or "auto").strip()
        self.quality = str(quality or "auto").strip()
        self.background = str(background or "auto").strip()
        self.output_format = str(output_format or "png").strip()
        self.output_compression = output_compression
        self.moderation = str(moderation or "auto").strip()
        self.stream_images = bool(stream_images)
        self.stream_partial_images = int(stream_partial_images or 2)
        self.edit_api_url = _normalize_image_edit_url(api_url)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_url": {
                "type": "str",
                "label": "Base URL",
                "default": "https://api.openai.com/v1",
            },
            "api_key": {
                "type": "password",
                "label": "OpenAI API key",
                "default": "",
            },
            "default_model": {
                "type": "str",
                "label": "Model",
                "default": "gpt-image-2",
            },
            "size": {
                "type": "str",
                "label": "Size",
                "default": "auto",
            },
            "quality": {
                "type": "select",
                "label": "Quality",
                "default": "auto",
                "choices": ["auto", "low", "medium", "high"],
            },
            "background": {
                "type": "select",
                "label": "Background",
                "default": "auto",
                "choices": ["auto", "transparent", "opaque"],
            },
            "output_format": {
                "type": "select",
                "label": "Output format",
                "default": "png",
                "choices": ["png", "jpeg", "webp"],
            },
            "output_compression": {
                "type": "int",
                "label": "Output compression",
                "default": 0,
                "min": 0,
                "max": 100,
                "step": 1,
            },
            "moderation": {
                "type": "select",
                "label": "Moderation",
                "default": "auto",
                "choices": ["auto", "low"],
            },
            "stream_images": {
                "type": "bool",
                "label": "Stream images",
                "default": False,
            },
            "stream_partial_images": {
                "type": "int",
                "label": "Stream partial images",
                "default": 2,
                "min": 0,
                "max": 3,
                "step": 1,
            },
            "timeout_s": {
                "type": "float",
                "label": "Timeout seconds",
                "default": 600.0,
                "min": 1.0,
                "max": 600.0,
                "step": 1.0,
            },
        }

    def _payload(self, prompt: str, **kwargs) -> dict[str, Any]:
        payload = super()._payload(prompt, api_format="openai", **kwargs)
        size = str(kwargs.get("size") or self.size or "").strip()
        quality = str(kwargs.get("quality") or self.quality or "").strip()
        background = str(kwargs.get("background") or self.background or "").strip()
        output_format = str(kwargs.get("output_format") or self.output_format or "").strip()
        moderation = str(kwargs.get("moderation") or self.moderation or "").strip()
        output_compression = kwargs.get("output_compression", self.output_compression)
        stream_images = kwargs.get("stream_images", self.stream_images)
        stream_partial_images = int(kwargs.get("stream_partial_images", self.stream_partial_images) or 2)
        if size:
            payload["size"] = size
        if quality:
            payload["quality"] = quality
        if background and background != "auto":
            payload["background"] = background
        if output_format:
            payload["output_format"] = output_format
        if moderation:
            payload["moderation"] = moderation
        if output_format != "png" and output_compression not in (None, "", 0, "0"):
            payload["output_compression"] = int(output_compression)
        if bool(stream_images):
            payload["stream"] = True
            payload["partial_images"] = max(0, min(3, stream_partial_images))
        if int(payload.get("n", 1) or 1) <= 1:
            payload.pop("n", None)
        return payload

    def generate_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        if not self.api_key:
            print("OpenAI GPT Image generation failed: missing OPENAI_API_KEY or api_key.")
            return None
        reference_image_path = str(kwargs.pop("reference_image_path", "") or "").strip()
        if reference_image_path:
            return self._generate_image_edit(prompt, reference_image_path, file_path, **kwargs)
        payload = self._payload(prompt, **kwargs)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
            image_data = self._first_image_bytes(data)
            if image_data is None:
                print("OpenAI image API returned no usable image payload.")
                return None
            if not file_path:
                file_path = os.path.join(os.getcwd(), "temp_openai_image.png")
            with open(file_path, "wb") as f:
                f.write(image_data)
            return os.path.abspath(file_path)
        except Exception as e:
            print(f"OpenAI GPT Image generation failed: {e}")
            return None

    def _generate_image_edit(
        self,
        prompt: str,
        reference_image_path: str,
        file_path: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        image_path = Path(reference_image_path).expanduser()
        if not image_path.is_file():
            print(f"OpenAI GPT Image edit failed: missing reference image {reference_image_path}")
            return None
        payload = self._payload(prompt, **kwargs)
        payload.pop("n", None)
        form = {
            "model": str(payload.get("model") or self.current_model or ""),
            "prompt": prompt,
            "size": str(payload.get("size") or "auto"),
            "output_format": str(payload.get("output_format") or "png"),
            "moderation": str(payload.get("moderation") or "auto"),
        }
        if payload.get("quality"):
            form["quality"] = str(payload["quality"])
        if payload.get("background"):
            form["background"] = str(payload["background"])
        if payload.get("output_compression") is not None:
            form["output_compression"] = str(payload["output_compression"])
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with image_path.open("rb") as handle:
                files = {"image[]": (image_path.name, handle, mime_type)}
                response = requests.post(
                    self.edit_api_url,
                    data=form,
                    files=files,
                    headers=headers,
                    timeout=self.timeout_s,
                )
            response.raise_for_status()
            data = response.json()
            image_data = self._first_image_bytes(data)
            if image_data is None:
                print("OpenAI image edit API returned no usable image payload.")
                return None
            if not file_path:
                file_path = os.path.join(os.getcwd(), "temp_openai_image.png")
            with open(file_path, "wb") as f:
                f.write(image_data)
            return os.path.abspath(file_path)
        except Exception as e:
            print(f"OpenAI GPT Image edit failed: {e}")
            return None
