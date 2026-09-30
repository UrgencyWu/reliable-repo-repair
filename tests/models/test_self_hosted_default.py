import pytest

from agent.dashboard.options import default_model_pair


@pytest.mark.parametrize("effort", ["", "none", "high"])
def test_self_hosted_default_requires_explicit_endpoint(
    monkeypatch: pytest.MonkeyPatch, effort: str
) -> None:
    monkeypatch.setenv("LLM_MODEL_ID", "openai:qwen3.8-27b")
    monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    with pytest.raises(ValueError, match="Unsupported default"):
        default_model_pair()
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8100/v1")
    assert default_model_pair() == ("openai:qwen3.8-27b", effort or "none")


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        ("openai:qwen3.8-27b", "invalid"),
        ("openai:", "none"),
        ("unknown:qwen3.8-27b", "none"),
        ("openai:gpt-5.5", "none"),
        ("anthropic:claude-fable-5-1", "high"),
    ],
)
def test_custom_endpoint_does_not_bypass_invalid_default(
    monkeypatch: pytest.MonkeyPatch, model: str, effort: str
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8100/v1")
    monkeypatch.setenv("LLM_MODEL_ID", model)
    monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    with pytest.raises(ValueError, match="Unsupported"):
        default_model_pair()
