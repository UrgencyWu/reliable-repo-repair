"""Test-only model boundary; the graph factory and execution tools remain upstream."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))

from langchain_core.language_models import BaseChatModel  # noqa: E402

from agent import server  # noqa: E402
from tests.e2e.fake_llm import FakeScriptedChatModel  # noqa: E402


def fake_make_model(model_id: str, **kwargs: object) -> BaseChatModel:  # noqa: ARG001
    return FakeScriptedChatModel()


server.make_model = fake_make_model
traced_agent = server.traced_agent

__all__ = ["traced_agent"]
