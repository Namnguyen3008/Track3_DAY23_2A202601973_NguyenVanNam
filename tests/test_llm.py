import importlib
import sys
import types

from langgraph_agent_lab import llm


def test_gemini_factory_rotates_implicit_models(monkeypatch):
    created = []

    class FakeGemini:
        def __init__(self, **kwargs):
            created.append(kwargs)

    fake_provider = types.ModuleType("langchain_google_genai")
    fake_provider.ChatGoogleGenerativeAI = FakeGemini
    monkeypatch.setitem(sys.modules, "langchain_google_genai", fake_provider)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    importlib.reload(llm)
    llm.get_llm()
    llm.get_llm()

    assert [item["model"] for item in created] == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
    ]
    assert all(item["temperature"] == 0.0 for item in created)


def test_explicit_gemini_model_bypasses_rotation(monkeypatch):
    created = []

    class FakeGemini:
        def __init__(self, **kwargs):
            created.append(kwargs)

    fake_provider = types.ModuleType("langchain_google_genai")
    fake_provider.ChatGoogleGenerativeAI = FakeGemini
    monkeypatch.setitem(sys.modules, "langchain_google_genai", fake_provider)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    importlib.reload(llm)
    llm.get_llm(model="gemini-test-model", temperature=0.2)

    assert created[0]["model"] == "gemini-test-model"
    assert created[0]["temperature"] == 0.2
