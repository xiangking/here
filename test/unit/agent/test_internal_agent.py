from __future__ import annotations

import types

import internal_agent.agent as agent_module
from internal_agent.agent import InternalAgent, InternalAgentModelError
from internal_agent.memory import build_identity_prompt
from internal_agent.memory_tool import run as run_memory_tool
from internal_agent.session_search import search
from internal_agent.session_store import SessionStore


def test_internal_agent_builds_identity_prompt_from_explicit_memory_home(monkeypatch, tmp_path):
    home = tmp_path / "agent"
    memories = home / "memories"
    memories.mkdir(parents=True)
    (home / "SOUL.md").write_text("# Alice\n角色设定", encoding="utf-8")
    (memories / "MEMORY.md").write_text("喜欢红茶\n§\n住在海边", encoding="utf-8")
    (memories / "USER.md").write_text("- 用户喜欢夜间散步\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "must_not_be_used"))

    prompt = build_identity_prompt(
        memory_home=home,
        load_soul_identity=True,
        skip_memory=False,
    )

    assert "# Alice" in prompt
    assert "喜欢红茶" in prompt
    assert "用户喜欢夜间散步" in prompt


def test_internal_agent_session_search_uses_explicit_memory_home(monkeypatch, tmp_path):
    home = tmp_path / "data" / "agent_memory" / "agents" / "Alice"
    store = SessionStore(tmp_path / "data" / "agent_memory")
    store.replace_messages(
        "past_session",
        [
            {"role": "user", "content": "昨天 Alice 和用户聊到了海边烟花。"},
            {"role": "assistant", "content": "我记得那场烟花。"},
        ],
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "must_not_be_used"))

    result = search("烟花", memory_home=home)

    assert "past_session" in result
    assert "海边烟花" in result


def test_internal_agent_session_search_finds_sqlite_session_and_excludes_current(tmp_path):
    home = tmp_path / "agent_memory" / "agents" / "Alice"
    store = SessionStore(tmp_path / "agent_memory")
    store.replace_messages(
        "past_session",
        [
            {"role": "user", "content": "刚才我们聊到了炒饭"},
            {"role": "assistant", "content": "我记得，你说正在准备吃炒饭。"},
        ],
    )
    store.replace_messages(
        "current_session",
        [
            {"role": "user", "content": "当前会话提到炒饭"},
            {"role": "assistant", "content": "当前会话内容应该靠 history。"},
        ],
    )

    result = search("炒饭", memory_home=home, current_session_id="current_session")

    assert "past_session" in result
    assert "current_session" not in result
    assert "刚才我们聊到了炒饭" in result


def test_internal_agent_stream_skips_empty_choice_chunks(monkeypatch):
    class _ChatCompletions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            return iter(
                [
                    types.SimpleNamespace(choices=[]),
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(content="hello", tool_calls=None)
                            )
                        ]
                    ),
                    types.SimpleNamespace(choices=[]),
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(content=" world", tool_calls=None)
                            )
                        ]
                    ),
                ]
            )

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=_ChatCompletions()
            )

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    chunks: list[str] = []
    agent = InternalAgent(api_key="test", model="test-model")

    result = agent.run_conversation("hi", stream_callback=chunks.append)

    assert chunks == ["hello", " world"]
    assert result["final_response"] == "hello world"


def test_internal_agent_stream_handles_reasoning_and_reused_tool_index(monkeypatch):
    class _ChatCompletions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            return iter(
                [
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(
                                    content=None,
                                    reasoning_content="thinking",
                                    reasoning=None,
                                    tool_calls=None,
                                )
                            )
                        ]
                    ),
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(
                                    content=None,
                                    tool_calls=[
                                        types.SimpleNamespace(
                                            index=0,
                                            id="call_1",
                                            function=types.SimpleNamespace(
                                                name="session_search",
                                                arguments='{"query": "one"}',
                                            ),
                                        )
                                    ],
                                )
                            )
                        ]
                    ),
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(
                                    content=None,
                                    tool_calls=[
                                        types.SimpleNamespace(
                                            index=0,
                                            id="call_2",
                                            function=types.SimpleNamespace(
                                                name="session_search",
                                                arguments='{"query": "two"}',
                                            ),
                                        )
                                    ],
                                )
                            )
                        ]
                    ),
                ]
            )

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=_ChatCompletions())

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    reasoning: list[str] = []
    agent = InternalAgent(
        api_key="test",
        model="test-model",
        enabled_toolsets=[],
        reasoning_callback=reasoning.append,
    )

    message = agent._request([], tools=None, stream_callback=lambda _text: None)

    assert reasoning == ["thinking"]
    assert message["reasoning_content"] == "thinking"
    assert [call["id"] for call in message["tool_calls"]] == ["call_1", "call_2"]
    assert message["tool_calls"][0]["function"]["arguments"] == '{"query": "one"}'
    assert message["tool_calls"][1]["function"]["arguments"] == '{"query": "two"}'


def test_internal_agent_non_stream_normalizes_content_list(monkeypatch):
    class _ChatCompletions:
        def create(self, **kwargs):
            assert "stream" not in kwargs
            message = types.SimpleNamespace(
                role="assistant",
                content=[
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": "ignored"}},
                    {"text": "world"},
                ],
            )
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=_ChatCompletions())

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    agent = InternalAgent(api_key="test", model="test-model")

    result = agent.run_conversation("hi")

    assert result["final_response"] == "hello\nworld"


def test_internal_agent_non_stream_rejects_empty_choices(monkeypatch):
    class _ChatCompletions:
        def create(self, **kwargs):
            return types.SimpleNamespace(choices=[])

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=_ChatCompletions())

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    agent = InternalAgent(api_key="test", model="test-model")

    try:
        agent.run_conversation("hi")
    except RuntimeError as exc:
        assert "did not include choices" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_internal_agent_exposes_memory_and_session_search_tools():
    agent = InternalAgent(
        api_key="test",
        model="test-model",
        enabled_toolsets=["memory", "session_search"],
    )

    tools = agent._build_tools()

    assert [tool["function"]["name"] for tool in tools] == ["memory", "session_search"]


def test_internal_agent_preserves_tool_calls_in_history():
    agent = InternalAgent(api_key="test", model="test-model")

    messages = agent._build_messages(
        user_message="continue",
        system_message=None,
        conversation_history=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_memory",
                        "type": "function",
                        "function": {"name": "memory", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_memory",
                "name": "memory",
                "content": '{"success": true}',
            },
        ],
    )

    assert messages[0]["tool_calls"][0]["id"] == "call_memory"
    assert messages[1]["tool_call_id"] == "call_memory"


def test_internal_agent_memory_tool_add_replace_remove(tmp_path):
    home = tmp_path / "agent"

    added = run_memory_tool(
        action="add",
        target="memory",
        content="用户喜欢直接指出问题。",
        memory_home=home,
    )
    replaced = run_memory_tool(
        action="replace",
        target="memory",
        old_text="直接指出问题",
        content="用户喜欢直接指出架构问题。",
        memory_home=home,
    )
    user_added = run_memory_tool(
        action="add",
        target="user",
        content="用户使用中文交流。",
        memory_home=home,
    )
    removed = run_memory_tool(
        action="remove",
        target="memory",
        old_text="架构问题",
        memory_home=home,
    )

    memory_text = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    user_text = (home / "memories" / "USER.md").read_text(encoding="utf-8")
    assert '"success": true' in added
    assert '"success": true' in replaced
    assert '"success": true' in user_added
    assert '"success": true' in removed
    assert "架构问题" not in memory_text
    assert "用户使用中文交流。" in user_text


def test_internal_agent_runs_memory_tool_from_non_stream_response(monkeypatch, tmp_path):
    class _ChatCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert any(tool["function"]["name"] == "memory" for tool in kwargs["tools"])
            if self.calls == 1:
                message = types.SimpleNamespace(
                    role="assistant",
                    content="",
                    tool_calls=[
                        types.SimpleNamespace(
                            id="call_memory",
                            type="function",
                            function=types.SimpleNamespace(
                                name="memory",
                                arguments='{"action":"add","target":"user","content":"用户喜欢简洁回答。"}',
                            ),
                        )
                    ],
                )
            else:
                message = types.SimpleNamespace(role="assistant", content="记好了。")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    completions = _ChatCompletions()

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=completions)

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    agent = InternalAgent(
        api_key="test",
        model="test-model",
        enabled_toolsets=["memory"],
        memory_home=tmp_path / "agent",
    )

    result = agent.run_conversation("记住我喜欢简洁回答")

    assert result["final_response"] == "记好了。"
    user_text = (tmp_path / "agent" / "memories" / "USER.md").read_text(encoding="utf-8")
    assert "用户喜欢简洁回答。" in user_text


def test_internal_agent_retries_without_tools_when_provider_rejects_tools(monkeypatch):
    class _ChatCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if "tools" in kwargs:
                raise RuntimeError("unsupported parameter: 'tools'")
            message = types.SimpleNamespace(role="assistant", content="纯聊天回复。")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    completions = _ChatCompletions()

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=completions)

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    statuses: list[str] = []
    agent = InternalAgent(
        api_key="test",
        model="test-model",
        enabled_toolsets=["memory"],
        status_callback=statuses.append,
    )

    result = agent.run_conversation("hi")

    assert result["final_response"] == "纯聊天回复。"
    assert len(completions.calls) == 2
    assert "tools" in completions.calls[0]
    assert "tools" not in completions.calls[1]
    assert statuses == ["当前 Internal Agent API 不支持 tools，已自动改为纯聊天模式。"]


def test_internal_agent_raises_clear_error_when_model_is_unavailable(monkeypatch):
    class _ChatCompletions:
        def create(self, **kwargs):
            raise RuntimeError(
                'Error code: 404 - {"error": {"message": "The model does not exist", "type": "model_invalid"}}'
            )

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=_ChatCompletions())

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    agent = InternalAgent(api_key="test", model="missing-model")

    try:
        agent.run_conversation("hi")
    except InternalAgentModelError as exc:
        assert "missing-model" in str(exc)
        assert "获取可用模型" in str(exc)
    else:
        raise AssertionError("expected InternalAgentModelError")


def test_internal_agent_persists_full_tool_conversation_to_session_store(monkeypatch, tmp_path):
    class _ChatCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                message = types.SimpleNamespace(
                    role="assistant",
                    content="",
                    tool_calls=[
                        types.SimpleNamespace(
                            id="call_search",
                            type="function",
                            function=types.SimpleNamespace(
                                name="session_search",
                                arguments='{"query":"炒饭"}',
                            ),
                        )
                    ],
                )
            else:
                assert kwargs["messages"][-1]["role"] == "tool"
                message = types.SimpleNamespace(role="assistant", content="查过了。")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    completions = _ChatCompletions()

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=completions)

    monkeypatch.setattr(agent_module, "OpenAI", _OpenAI)
    store = SessionStore(tmp_path / "agent_memory")
    agent = InternalAgent(
        api_key="test",
        model="test-model",
        enabled_toolsets=["session_search"],
        memory_home=tmp_path / "agent_memory" / "agents" / "Alice",
        session_store=store,
        session_id="current_session",
    )

    result = agent.run_conversation("查一下炒饭")
    stored = store.get_messages_as_conversation("current_session")

    assert result["messages"][0] == {"role": "user", "content": "查一下炒饭"}
    assert result["messages"][1]["tool_calls"][0]["id"] == "call_search"
    assert result["messages"][2]["role"] == "tool"
    assert result["messages"][3] == {"role": "assistant", "content": "查过了。"}
    assert stored[0] == result["messages"][0]
    assert stored[1] == result["messages"][1]
    assert stored[2]["role"] == "tool"
    assert stored[2]["tool_call_id"] == "call_search"
    assert stored[2]["tool_name"] == "session_search"
    assert stored[3] == result["messages"][3]
