"""fal OpenRouter routing: endpoint choice, temperature handling, and the language routes."""
import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fal_client.client import Completed

from app.api import generation as generation_api
from app.api import settings as settings_api
from app.providers import fal_vision_provider as fvp
from app.providers.fal_vision_provider import (
    FalClusterSummarizer,
    FalVisionDescriber,
    FalVisionEvaluator,
    FalVisionTagger,
    fal_text_completion,
)
from app.services.model_catalog import DEFAULT_LANGUAGE_MODEL, LANGUAGE_MODELS

ROUTER = "openrouter/router"
VISION = "openrouter/router/vision"
NO_TEMP = [m for m in LANGUAGE_MODELS if not m.supports_temperature]
WITH_TEMP = [m for m in LANGUAGE_MODELS if m.supports_temperature]
ALL_JSON = json.dumps({
    "tags": ["a"], "description": "d", "summary_title": "Title", "summary_description": "- one",
    "style_fidelity": 5, "subject_accuracy": 5, "detail_preservation": 5, "overall": 5, "assessment": "ok",
    "realism": 5, "prompt_adherence": 5, "detail_quality": 5, "summary": "sum", "prompts": ["p1", "p2"],
})


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fal_submit(monkeypatch):
    handle = Mock()
    handle.request_id = "req-1"
    handle.status.return_value = Completed(logs=None, metrics={})
    handle.get.return_value = {
        "output": ALL_JSON,
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.0004},
    }
    submit = Mock(return_value=handle)
    monkeypatch.setattr(fvp, "fal_client", SimpleNamespace(submit=submit))
    monkeypatch.setattr(fvp, "write_log", Mock())
    return submit


def _sent(fal_submit):
    endpoint, = fal_submit.call_args.args
    return endpoint, fal_submit.call_args.kwargs["arguments"]


def _vision_calls(model_id, temperature=0.7):
    """(label, awaitable factory) for every image-bearing operation."""
    png = b"\x89PNG"
    tagger = FalVisionTagger(model=model_id, temperature=temperature)
    describer = FalVisionDescriber(model=model_id, temperature=temperature)
    evaluator = FalVisionEvaluator(model=model_id, temperature=temperature)
    return [
        ("tag", lambda: tagger.tag_image(png, "image/png", "tag it")),
        ("describe", lambda: describer.describe_image(png, "image/png", "describe it")),
        ("evaluate_pair", lambda: evaluator.evaluate_pair(png, png, "image/png", "image/png", "prompt")),
        ("evaluate_single", lambda: evaluator.evaluate_single(png, "image/png", "prompt")),
    ]


def _text_calls(model_id, temperature=0.7):
    evaluator = FalVisionEvaluator(model=model_id, temperature=temperature)
    summarizer = FalClusterSummarizer(model=model_id)
    return [
        ("summarize_assessments", lambda: evaluator.summarize_assessments("m", "t", [{"score": 1, "assessment": "a"}], 1, 1, 1)),
        ("generate_creative_prompts", lambda: evaluator.generate_creative_prompts("t", ["d"], 2)),
        ("summarize_cluster", lambda: summarizer.summarize_cluster(["a"], ["d"], 3)),
    ]


@pytest.mark.parametrize("model", NO_TEMP, ids=lambda m: m.id)
def test_temperature_is_omitted_when_the_model_does_not_support_it(fal_submit, model):
    for label, call in _vision_calls(model.id):
        run(call())
        endpoint, args = _sent(fal_submit)
        assert endpoint == VISION, label
        assert "temperature" not in args, f"{model.id} {label}"
        assert args["model"] == model.id


@pytest.mark.parametrize("model", WITH_TEMP, ids=lambda m: m.id)
def test_temperature_is_sent_when_the_model_supports_it(fal_submit, model):
    for label, call in _vision_calls(model.id):
        run(call())
        _, args = _sent(fal_submit)
        assert args["temperature"] == 0.7, f"{model.id} {label}"
    run(_text_calls(model.id)[0][1]())
    assert _sent(fal_submit)[1]["temperature"] == 0.7


def test_text_only_calls_use_the_text_router_and_vision_calls_the_vision_router(fal_submit):
    for label, call in _text_calls(DEFAULT_LANGUAGE_MODEL):
        run(call())
        endpoint, args = _sent(fal_submit)
        assert endpoint == ROUTER, label
        assert "image_urls" not in args, label
    for label, call in _vision_calls(DEFAULT_LANGUAGE_MODEL):
        run(call())
        endpoint, args = _sent(fal_submit)
        assert endpoint == VISION, label
        assert args["image_urls"], label


def test_unknown_model_omits_temperature():
    _, args = fvp.build_router_request("someone/new-model", "hi", 10, temperature=0.5)
    assert "temperature" not in args


def test_cluster_summarizer_returns_the_parsed_result_and_logs_summarize(fal_submit):
    result = run(FalClusterSummarizer(model=DEFAULT_LANGUAGE_MODEL).summarize_cluster(["a", "b"], ["d1", "d2"], 4))

    assert result.summary_title == "Title"
    assert result.summary_description == "- one"
    assert result.model == DEFAULT_LANGUAGE_MODEL
    log = fvp.write_log.call_args.kwargs
    assert (log["provider"], log["operation"], log["model"]) == ("fal", "summarize", DEFAULT_LANGUAGE_MODEL)
    assert (log["input_tokens"], log["output_tokens"], log["provider_cost"]) == (11, 7, 0.0004)


def test_fal_text_completion_returns_text_and_usage(fal_submit):
    fal_submit.return_value.get.return_value["reasoning"] = "private reasoning"
    completion = run(fal_text_completion(
        "hello", "openai/gpt-6-luna", 50, system_prompt="be brief", temperature=0.4,
    ))

    endpoint, args = _sent(fal_submit)
    assert endpoint == ROUTER
    assert args == {"prompt": "hello", "model": "openai/gpt-6-luna", "max_tokens": 50, "system_prompt": "be brief"}
    assert completion.text == ALL_JSON
    assert completion.input_tokens == 11
    assert completion.output_tokens == 7
    assert completion.provider_cost == 0.0004


# --- Routes ---


class FakeBillable:
    """Stands in for the billing boundary and records how it was used."""

    def __init__(self):
        self.calls = []
        self.actuals = []

    @contextmanager
    def __call__(self, db, user_id, operation, provider, model, **kwargs):
        self.calls.append({"operation": operation, "provider": provider, "model": model, **kwargs})
        ctx = SimpleNamespace(set_actual=lambda **kw: self.actuals.append(kw))
        yield ctx


@pytest.fixture
def route_env(monkeypatch, fal_submit):
    fake_billable = FakeBillable()
    monkeypatch.setattr("app.services.billing_decorator.billable", fake_billable)
    monkeypatch.setattr("app.services.billing_service.BillingService", MagicMock())
    config = {"fal_language_model": "openai/gpt-6.1-terra", "max_tokens_expansion": 321, "max_tokens_suggestion": 654}
    monkeypatch.setattr("app.providers._resolve_config", lambda db, user_id: ({"fal": "test-key"}, config))
    return SimpleNamespace(billable=fake_billable, submit=fal_submit, config=config)


def test_expand_prompt_calls_fal_with_the_selected_model_and_bills_it(route_env):
    route_env.submit.return_value.get.return_value = {"output": "  a vivid fox  ", "usage": {"prompt_tokens": 5, "completion_tokens": 9}}

    response = run(generation_api.expand_prompt(
        generation_api.ExpandPromptRequest(prompt="fox"), db=MagicMock(), current_user=SimpleNamespace(id=7),
    ))

    assert response.expanded_prompt == "a vivid fox"
    endpoint, args = _sent(route_env.submit)
    assert endpoint == ROUTER
    assert args["model"] == "openai/gpt-6.1-terra"
    assert args["max_tokens"] == 321
    assert args["prompt"] == "fox"
    assert "temperature" not in args
    (call,) = route_env.billable.calls
    assert (call["operation"], call["provider"], call["model"]) == ("expand_prompt", "fal", "openai/gpt-6.1-terra")
    (actual,) = route_env.billable.actuals
    assert (actual["input_tokens"], actual["output_tokens"]) == (5, 9)


def test_suggest_prompt_calls_fal_with_the_selected_model_and_bills_it(route_env):
    route_env.submit.return_value.get.return_value = {"output": "new prompt", "usage": {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.001}}

    response = run(settings_api.suggest_prompt(
        settings_api.PromptSuggestRequest(current_prompt="old", change_request="shorter", prompt_type="tag"),
        db=MagicMock(), current_user=SimpleNamespace(id=7),
    ))

    assert response.suggested_prompt == "new prompt"
    endpoint, args = _sent(route_env.submit)
    assert endpoint == ROUTER
    assert args["model"] == "openai/gpt-6.1-terra"
    assert args["max_tokens"] == 654
    assert "Current prompt:\nold" in args["prompt"]
    (call,) = route_env.billable.calls
    assert (call["operation"], call["provider"], call["model"]) == ("suggest_prompt", "fal", "openai/gpt-6.1-terra")
    (actual,) = route_env.billable.actuals
    assert actual["provider_cost"] == 0.001


@pytest.mark.parametrize("route", ["expand", "suggest"])
def test_language_routes_report_a_missing_fal_key(monkeypatch, route):
    monkeypatch.setattr("app.services.billing_service.BillingService", MagicMock())
    monkeypatch.setattr("app.providers._resolve_config", lambda db, user_id: ({"fal": None}, {}))

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        if route == "expand":
            run(generation_api.expand_prompt(
                generation_api.ExpandPromptRequest(prompt="fox"), db=MagicMock(), current_user=SimpleNamespace(id=7),
            ))
        else:
            run(settings_api.suggest_prompt(
                settings_api.PromptSuggestRequest(current_prompt="o", change_request="c", prompt_type="tag"),
                db=MagicMock(), current_user=SimpleNamespace(id=7),
            ))
    assert exc.value.status_code == 400
    assert "fal" in exc.value.detail


def test_route_helper_does_not_block_the_event_loop(fal_submit):
    # The blocking submit/poll runs in a worker thread, so the loop stays responsive.
    import threading

    seen = {}

    def submit(*_a, **_k):
        seen["thread"] = threading.current_thread()
        return fal_submit.return_value

    fal_submit.side_effect = submit
    run(fal_text_completion("x", DEFAULT_LANGUAGE_MODEL, 10))
    assert seen["thread"] is not threading.main_thread()


@pytest.mark.parametrize("image_urls", [None, ["data:image/png;base64,AA=="]])
def test_mandatory_reasoning_is_enabled_for_text_and_vision(image_urls):
    from app.providers.fal_vision_provider import build_router_request
    from app.services.model_catalog import LANGUAGE_MODELS

    mandatory = [model for model in LANGUAGE_MODELS if model.requires_reasoning]
    assert len(mandatory) == 13
    for model in LANGUAGE_MODELS:
        endpoint, payload = build_router_request(model.id, "Return JSON", 128, image_urls=image_urls, temperature=0.2)
        assert endpoint.endswith("/vision") == bool(image_urls)
        if model.requires_reasoning:
            assert payload["reasoning"] is True
            assert payload["max_tokens"] >= 4096
        else:
            assert "reasoning" not in payload
