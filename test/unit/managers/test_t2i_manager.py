"""Unit tests for T2IManager — factory, queue behavior, adapter switching."""

import base64
import time
from pathlib import Path

import pytest

from services.t2i.t2i_manager import T2IManager, T2IAdapterFactory
from services.t2i.t2i_adapter import OpenAIGPTImageAdapter, XAIGrokImagineAdapter
from test.mocks import MockT2IAdapter


class TestT2IAdapterFactoryRegistry:
    def test_all_registered_adapters_present(self):
        assert "image-api" in T2IAdapterFactory._adapters
        assert "xai-grok-imagine" in T2IAdapterFactory._adapters
        assert "openai-gpt-image" in T2IAdapterFactory._adapters

    def test_unknown_adapter_raises(self):
        with pytest.raises(ValueError, match="Unsupported T2I adapter"):
            T2IAdapterFactory.create_adapter("nonexistent-t2i")

    def test_factory_can_be_injected_with_mock(self):
        """Register a mock adapter in the factory dict and create via factory."""
        T2IAdapterFactory._adapters["mock-t2i"] = MockT2IAdapter
        try:
            adapter = T2IAdapterFactory.create_adapter("mock-t2i")
            assert isinstance(adapter, MockT2IAdapter)
        finally:
            del T2IAdapterFactory._adapters["mock-t2i"]

    def test_openai_gpt_image_payload_includes_image_options(self):
        adapter = OpenAIGPTImageAdapter(api_key="sk-test", default_model="gpt-image-2")

        payload = adapter._payload("selfie")

        assert payload["model"] == "gpt-image-2"
        assert payload["size"] == "auto"
        assert payload["quality"] == "auto"
        assert "background" not in payload
        assert payload["output_format"] == "png"
        assert payload["moderation"] == "auto"
        assert "n" not in payload

    def test_openai_gpt_image_payload_keeps_explicit_background_and_compression(self):
        adapter = OpenAIGPTImageAdapter(
            api_key="sk-test",
            background="transparent",
            output_format="webp",
            output_compression=70,
        )

        payload = adapter._payload("selfie", size="1024x1024", n=2)

        assert payload["size"] == "1024x1024"
        assert payload["background"] == "transparent"
        assert payload["output_compression"] == 70
        assert payload["n"] == 2

    def test_openai_gpt_image_accepts_base_url(self):
        adapter = OpenAIGPTImageAdapter(api_url="https://maolaoapi.com", api_key="sk-test")

        assert adapter.api_url == "https://maolaoapi.com/v1/images/generations"
        assert adapter.edit_api_url == "https://maolaoapi.com/v1/images/edits"

    def test_xai_grok_imagine_schema_exposes_api_url(self):
        schema = XAIGrokImagineAdapter.get_config_schema()

        assert schema["api_url"]["default"] == "https://fal.run/xai/grok-imagine-image/edit"
        assert schema["api_key"]["type"] == "password"
        assert "api_style" in schema
        assert "openrouter" in schema["api_style"]["choices"]
        assert schema["default_model"]["default"] == "xai/grok-imagine-image"

    def test_xai_grok_imagine_uses_fal_edit_url_for_fal_endpoint(self):
        adapter = XAIGrokImagineAdapter(api_url="https://fal.run", api_key="key")

        assert adapter.api_url == "https://fal.run/xai/grok-imagine-image/edit"
        assert adapter.fal_generation_url == "https://fal.run/xai/grok-imagine-image"
        assert adapter.fal_edit_url == "https://fal.run/xai/grok-imagine-image/edit"
        assert adapter.fal_application == "xai/grok-imagine-image"

    def test_xai_grok_imagine_accepts_full_fal_edit_url(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://fal.run/xai/grok-imagine-image/edit",
            api_key="key",
        )

        assert adapter.api_url == "https://fal.run/xai/grok-imagine-image/edit"
        assert adapter.fal_proxy_url == "https://fal.run"
        assert adapter.fal_application == "xai/grok-imagine-image"
        assert adapter.fal_generation_url == "https://fal.run/xai/grok-imagine-image"
        assert adapter.fal_edit_url == "https://fal.run/xai/grok-imagine-image/edit"

    def test_xai_grok_imagine_respects_custom_fal_style_url(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://example.com/xai/grok-imagine-image/edit",
            api_key="key",
        )

        assert adapter.api_url == "https://example.com/xai/grok-imagine-image/edit"
        assert adapter.fal_proxy_url == "https://example.com"
        assert adapter.fal_edit_url == "https://example.com/xai/grok-imagine-image/edit"
        assert not adapter._uses_official_fal_client()

    def test_xai_grok_imagine_model_overrides_default_full_url_endpoint(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://fal.run/xai/grok-imagine-image/edit",
            api_key="key",
            default_model="custom/image-model",
        )

        assert adapter.fal_application == "custom/image-model"
        assert adapter.fal_generation_url == "https://fal.run/custom/image-model"
        assert adapter.fal_edit_url == "https://fal.run/custom/image-model/edit"

    def test_xai_grok_imagine_maps_legacy_model_name_to_endpoint(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://fal.run",
            api_key="key",
            default_model="grok-imagine-image-quality",
        )

        assert adapter.fal_application == "xai/grok-imagine-image"
        assert adapter.fal_edit_url == "https://fal.run/xai/grok-imagine-image/edit"

    def test_xai_grok_imagine_keeps_openai_compatible_endpoint(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://maolaoapi.com/v1/images/generations",
            api_key="key",
            api_style="openai",
        )

        assert adapter.api_url == "https://maolaoapi.com/v1/images/generations"

    def test_xai_grok_imagine_maps_openrouter_model_page_to_chat_endpoint(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://openrouter.ai/x-ai/grok-imagine-image-quality/api",
            api_key="sk-or-test",
            api_style="fal",
            default_model="xai/grok-imagine-image",
        )

        assert adapter.api_style == "openrouter"
        assert adapter.api_url == "https://openrouter.ai/api/v1/chat/completions"
        assert adapter.current_model == "x-ai/grok-imagine-image-quality"

    def test_xai_grok_imagine_uses_direct_openrouter_chat_endpoint(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://openrouter.ai/api/v1/chat/completions",
            api_key="sk-or-test",
            api_style="openrouter",
            default_model="x-ai/grok-imagine-image-quality",
        )

        assert adapter.api_url == "https://openrouter.ai/api/v1/chat/completions"
        assert adapter.current_model == "x-ai/grok-imagine-image-quality"

    def test_xai_grok_imagine_replaces_fal_default_model_for_direct_openrouter_endpoint(self):
        adapter = XAIGrokImagineAdapter(
            api_url="https://openrouter.ai/api/v1/chat/completions",
            api_key="sk-or-test",
            api_style="openrouter",
            default_model="xai/grok-imagine-image",
        )

        assert adapter.current_model == "x-ai/grok-imagine-image-quality"

    def test_xai_grok_imagine_builds_openrouter_payload_with_reference_image(self, tmp_path):
        adapter = XAIGrokImagineAdapter(
            api_url="https://openrouter.ai/x-ai/grok-imagine-image-quality/api",
            api_key="sk-or-test",
        )
        reference = tmp_path / "ref.png"
        reference.write_bytes(b"reference")

        payload = adapter._openrouter_payload(
            "natural daily selfie",
            reference_image_path=reference.as_posix(),
            aspect_ratio="16:9",
            image_size="2K",
        )

        assert payload["model"] == "x-ai/grok-imagine-image-quality"
        assert payload["modalities"] == ["image"]
        assert payload["image_config"] == {"aspect_ratio": "16:9", "image_size": "2K"}
        content = payload["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "natural daily selfie"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_xai_grok_imagine_writes_openrouter_response_image(self, tmp_path):
        adapter = XAIGrokImagineAdapter(
            api_url="https://openrouter.ai/x-ai/grok-imagine-image-quality/api",
            api_key="sk-or-test",
        )
        encoded = base64.b64encode(b"openrouter png").decode("ascii")

        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "images": [
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{encoded}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }

        calls = []

        def fake_post(url, json, headers, timeout):
            calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return FakeResponse()

        import services.t2i.t2i_adapter as t2i_adapter_module

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(t2i_adapter_module.requests, "post", fake_post)
            target = tmp_path / "here.png"

            result = adapter.generate_image("natural daily selfie", file_path=target.as_posix())
        finally:
            monkeypatch.undo()

        assert result == target.as_posix()
        assert target.read_bytes() == b"openrouter png"
        assert calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert calls[0]["headers"]["Authorization"] == "Bearer sk-or-test"
        assert calls[0]["json"]["model"] == "x-ai/grok-imagine-image-quality"
        assert calls[0]["json"]["messages"][0]["content"] == "natural daily selfie"

    def test_xai_grok_imagine_posts_fal_edit_payload_for_reference_url(self, tmp_path):
        adapter = XAIGrokImagineAdapter(api_url="https://fal.run", api_key="Key test-key")
        calls = []

        def fake_post(url, body, headers):
            calls.append({"url": url, "body": dict(body), "headers": dict(headers)})
            encoded = base64.b64encode(b"fake jpeg").decode("ascii")
            return {"images": [{"url": f"data:image/jpeg;base64,{encoded}"}]}

        adapter._post_json = fake_post
        target = tmp_path / "here.jpg"

        result = adapter.generate_image(
            "make a pic of this person, but at home",
            file_path=target.as_posix(),
            reference_image_path="https://example.com/here.png",
        )

        assert result == target.as_posix()
        assert target.read_bytes() == b"fake jpeg"
        assert calls[0]["url"] == "https://fal.run/xai/grok-imagine-image/edit"
        assert calls[0]["headers"]["Authorization"] == "Key test-key"
        assert calls[0]["body"] == {
            "image_url": "https://example.com/here.png",
            "prompt": "make a pic of this person, but at home",
            "num_images": 1,
            "output_format": "jpeg",
        }

    def test_xai_grok_imagine_uploads_local_reference_before_edit(self, tmp_path):
        adapter = XAIGrokImagineAdapter(api_url="https://fal.run", api_key="test-key")
        reference = tmp_path / "ref.png"
        reference.write_bytes(b"reference")
        calls = []

        adapter._upload_fal_reference_image = lambda path: "https://fal.media/ref.png"

        def fake_post(url, body, headers):
            calls.append({"url": url, "body": dict(body), "headers": dict(headers)})
            return {"images": [base64.b64encode(b"edited").decode("ascii")]}

        adapter._post_json = fake_post

        result = adapter.generate_image(
            "selfie",
            file_path=(tmp_path / "edited.jpg").as_posix(),
            reference_image_path=reference.as_posix(),
        )

        assert Path(result).read_bytes() == b"edited"
        assert calls[0]["body"]["image_url"] == "https://fal.media/ref.png"
        assert "image_urls" not in calls[0]["body"]


class TestT2IManagerWithMock:
    def test_init_starts_worker(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        assert mgr.worker_thread.is_alive()
        mgr.shutdown()

    def test_set_adapter(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        new_adapter = MockT2IAdapter()
        mgr.set_t2i_adapter(new_adapter)
        assert mgr.t2i_adapter is new_adapter
        mgr.shutdown()

    def test_t2i_calls_adapter_and_writes_file(self, mock_t2i_adapter, tmp_path):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        result = mgr.t2i(prompt="A beautiful sunset")
        assert result is not None
        assert Path(result).exists()
        assert len(mock_t2i_adapter.call_history) == 1
        assert mock_t2i_adapter.call_history[0]["prompt"] == "A beautiful sunset"
        mgr.shutdown()

    def test_t2i_no_adapter_returns_none(self):
        mgr = T2IManager(t2i_adapter=None)
        result = mgr.t2i(prompt="test")
        assert result is None
        mgr.shutdown()

    def test_t2i_cycles_cache_index(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.cache_num = 3
        for i in range(5):
            mgr.t2i(prompt=f"Prompt {i}")
        assert mgr.index == 5
        mgr.shutdown()

    def test_t2i_accepts_explicit_file_path_without_advancing_cache(self, mock_t2i_adapter, tmp_path):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        target = tmp_path / "selfies" / "alice.png"

        result = mgr.t2i(prompt="A selfie", file_path=target.as_posix())

        assert result == target.as_posix()
        assert target.exists()
        assert mgr.index == 0
        assert mock_t2i_adapter.call_history[0]["file_path"] == target.as_posix()
        mgr.shutdown()

    def test_switch_model_delegates(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.switch_model({"model": "sdxl"})
        assert any("switch_model" in str(c) for c in mock_t2i_adapter.call_history)
        mgr.shutdown()

    def test_switch_model_no_adapter_noop(self):
        mgr = T2IManager(t2i_adapter=None)
        mgr.switch_model({"model": "x"})  # should not raise
        mgr.shutdown()

    def test_shutdown_terminates_worker(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.shutdown()
        mgr.worker_thread.join(timeout=2)
        assert not mgr.worker_thread.is_alive()

    def test_init_creates_cache_dir(self, mock_t2i_adapter):
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        assert mgr.image_cache_dir.exists()
        mgr.shutdown()

    def test_queue_generation_processes_via_t2i(self, mock_t2i_adapter):
        """queue_generation puts a task; the worker calls t2i() to handle it."""
        mgr = T2IManager(t2i_adapter=mock_t2i_adapter)
        mgr.queue_generation(prompt="Queued generation", extra_param="value")
        time.sleep(0.2)
        assert len(mock_t2i_adapter.call_history) >= 1
        mgr.shutdown()
