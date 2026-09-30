from scripts.repair_real_model_acceptance import trajectory_usage


def test_usage_reads_runtime_serialized_metadata_without_counting_tool_messages() -> None:
    state: dict[str, object] = {
        "values": {
            "messages": [
                {
                    "type": "ai",
                    "usage_metadata": None,
                    "additional_kwargs": {
                        "usage_metadata": {
                            "input_tokens": 20,
                            "output_tokens": 3,
                            "total_tokens": 23,
                        }
                    },
                    "tool_calls": [{"name": "execute"}],
                    "response_metadata": {"model_name": "qwen3.8-27b"},
                },
                {"type": "tool", "content": "passed"},
            ]
        }
    }
    result = trajectory_usage(state)
    assert result["tokens"] == {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23}
    assert result["ai_messages"] == 1
    assert result["tool_calls"] == 1
    assert result["observed_models"] == ["qwen3.8-27b"]


def test_missing_usage_keeps_total_unknown_and_preserves_known_partial_count() -> None:
    state: dict[str, object] = {
        "values": {
            "messages": [
                {
                    "type": "ai",
                    "usage_metadata": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                },
                {"type": "ai", "usage_metadata": None},
            ]
        }
    }
    result = trajectory_usage(state)
    assert result["tokens"] is None
    assert result["messages_without_usage"] == 1
    assert result["known_partial_tokens"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
    }
