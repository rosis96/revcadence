"""Regression checks for GPT-5/legacy Chat Completions parameters."""
import json
import os

from app.enrichment import ai


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}


def run():
    captured = []
    original_post = ai.requests.post
    original_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "test-key"
    ai.requests.post = lambda *args, **kwargs: captured.append(kwargs["json"]) or _Response()
    try:
        assert ai._call_openai("system", "user", model="gpt-5-mini") == {"ok": True}
        gpt5 = captured[-1]
        assert gpt5["reasoning_effort"] == "low"
        assert "temperature" not in gpt5

        assert ai._call_openai("system", "user", model="gpt-4.1-mini") == {"ok": True}
        legacy = captured[-1]
        assert legacy["temperature"] == 0.2
        assert "reasoning_effort" not in legacy
    finally:
        ai.requests.post = original_post
        if original_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = original_key
    print("OK: 2 model-payload checks passed")


if __name__ == "__main__":
    run()
