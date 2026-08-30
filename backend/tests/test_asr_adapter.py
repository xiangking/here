from __future__ import annotations

import sys
import threading
import unittest
from unittest.mock import patch
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from services.asr.asr_adapter import VoskAdapter  # noqa: E402


class VoskAdapterTests(unittest.TestCase):
    def test_default_input_change_reopens_stream_on_new_device(self) -> None:
        adapter = VoskAdapter.__new__(VoskAdapter)
        selected_device = {"index": 1}
        opened_device_indexes = []

        class FakeStream:
            def __init__(self, device_index: int) -> None:
                self.device_index = device_index
                self.closed = False

            def start_stream(self) -> None:
                pass

            def read(self, _size, exception_on_overflow=False) -> bytes:
                if self.device_index == 1:
                    selected_device["index"] = 2
                else:
                    adapter._is_running = False
                return b"\x00\x00"

            def stop_stream(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        class FakeAudioEngine:
            def get_default_input_device_info(self):
                return {"index": selected_device["index"]}

            def open(self, **kwargs):
                device_index = kwargs["input_device_index"]
                opened_device_indexes.append(device_index)
                return FakeStream(device_index)

            def terminate(self) -> None:
                pass

        class FakePyAudio:
            paInt16 = 8

            @staticmethod
            def PyAudio():
                return FakeAudioEngine()

        class FakeRecognizer:
            def __init__(self, _model, _sample_rate) -> None:
                pass

            def AcceptWaveform(self, _data) -> bool:
                return False

            def PartialResult(self) -> str:
                return "{}"

        adapter.model = object()
        adapter._pyaudio = FakePyAudio
        adapter._KaldiRecognizer = FakeRecognizer
        adapter.samplerate = 16000
        adapter.chunk_size = 8192
        adapter._is_running = True
        adapter._stream = None
        adapter._startup_event = threading.Event()
        adapter._startup_error = None
        adapter._pause_event = threading.Event()
        adapter._pause_event.set()
        adapter.callback = lambda *_args, **_kwargs: None

        adapter._vosk_recognition_loop()

        self.assertEqual(opened_device_indexes, [1, 2])

    def test_stream_failure_reopens_audio_stream_while_running(self) -> None:
        adapter = VoskAdapter.__new__(VoskAdapter)
        opened_streams = []

        class FakeStream:
            def __init__(self, should_fail: bool) -> None:
                self.should_fail = should_fail
                self.closed = False

            def start_stream(self) -> None:
                pass

            def read(self, _size, exception_on_overflow=False) -> bytes:
                if self.should_fail:
                    raise OSError("device reset")
                adapter._is_running = False
                return b"\x00\x00"

            def stop_stream(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        class FakeAudioEngine:
            def open(self, **_kwargs):
                stream = FakeStream(not opened_streams)
                opened_streams.append(stream)
                return stream

            def terminate(self) -> None:
                pass

        class FakePyAudio:
            paInt16 = 8

            @staticmethod
            def PyAudio():
                return FakeAudioEngine()

        class FakeRecognizer:
            def __init__(self, _model, _sample_rate) -> None:
                pass

            def AcceptWaveform(self, _data) -> bool:
                return False

            def PartialResult(self) -> str:
                return "{}"

        adapter.model = object()
        adapter._pyaudio = FakePyAudio
        adapter._KaldiRecognizer = FakeRecognizer
        adapter.samplerate = 16000
        adapter.chunk_size = 8192
        adapter._is_running = True
        adapter._stream = None
        adapter._startup_event = threading.Event()
        adapter._startup_error = None
        adapter._pause_event = threading.Event()
        adapter._pause_event.set()
        adapter.callback = lambda *_args, **_kwargs: None

        with patch("services.asr.asr_adapter.time.sleep"):
            adapter._vosk_recognition_loop()

        self.assertEqual(len(opened_streams), 2)
        self.assertTrue(all(stream.closed for stream in opened_streams))

    def test_paused_loop_keeps_reading_and_discards_audio(self) -> None:
        adapter = VoskAdapter.__new__(VoskAdapter)

        class FakeStream:
            def __init__(self) -> None:
                self.read_count = 0

            def start_stream(self) -> None:
                pass

            def read(self, _size, exception_on_overflow=False) -> bytes:
                self.read_count += 1
                adapter._is_running = False
                return b"\x00\x00"

            def stop_stream(self) -> None:
                pass

            def close(self) -> None:
                pass

        class FakeAudioEngine:
            def __init__(self, stream) -> None:
                self.stream = stream

            def open(self, **_kwargs):
                return self.stream

            def terminate(self) -> None:
                pass

        stream = FakeStream()

        class FakePyAudio:
            paInt16 = 8

            @staticmethod
            def PyAudio():
                return FakeAudioEngine(stream)

        class FakeRecognizer:
            accept_count = 0

            def __init__(self, _model, _sample_rate) -> None:
                pass

            def AcceptWaveform(self, _data) -> bool:
                type(self).accept_count += 1
                return False

        adapter.model = object()
        adapter._pyaudio = FakePyAudio
        adapter._KaldiRecognizer = FakeRecognizer
        adapter.samplerate = 16000
        adapter.chunk_size = 8192
        adapter._is_running = True
        adapter._stream = None
        adapter._startup_event = threading.Event()
        adapter._startup_error = None
        adapter._pause_event = threading.Event()
        adapter.callback = lambda *_args, **_kwargs: None

        adapter._vosk_recognition_loop()

        self.assertEqual(stream.read_count, 1)
        self.assertEqual(FakeRecognizer.accept_count, 0)

    def test_stop_leaves_stream_cleanup_to_reader_thread_and_uses_bounded_join(self) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.stopped = False
                self.closed = False

            def stop_stream(self) -> None:
                self.stopped = True

            def close(self) -> None:
                self.closed = True

        class FakeThread:
            def __init__(self) -> None:
                self.join_timeout = None

            def is_alive(self) -> bool:
                return self.join_timeout is None

            def join(self, timeout=None) -> None:
                self.join_timeout = timeout

        adapter = VoskAdapter.__new__(VoskAdapter)
        stream = FakeStream()
        thread = FakeThread()
        adapter._is_running = True
        adapter._stream = stream
        adapter._thread = thread

        adapter.stop()

        self.assertFalse(adapter._is_running)
        self.assertFalse(stream.stopped)
        self.assertFalse(stream.closed)
        self.assertEqual(thread.join_timeout, 3)


if __name__ == "__main__":
    unittest.main()
