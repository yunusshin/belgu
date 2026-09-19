import json

import httpx
import pytest

from belgu.analysis.client import ModelClient, ModelClientError


SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def test_client_discovers_model_and_sends_bounded_schema_request_without_tools():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "verified-local-id",
                            "owned_by": "llama.cpp",
                            "meta": {"n_ctx_train": 262144},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "model": "verified-local-id",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"summary":"Türkçe"}'},
                    }
                ],
                "usage": {"prompt_tokens": 25, "completion_tokens": 8},
                "timings": {"prompt_ms": 20.0, "predicted_ms": 40.0},
            },
        )

    client = ModelClient(
        "http://127.0.0.1:8080/v1",
        "verified-local-id",
        transport=httpx.MockTransport(handler),
    )
    models = client.models()
    completion = client.complete(
        [{"role": "user", "content": "Özetle"}], SCHEMA, max_output_tokens=77
    )

    assert models[0].id == "verified-local-id"
    body = json.loads(seen[-1].content)
    assert body["max_tokens"] == 77
    assert body["temperature"] == 0
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "belgu_analysis", "strict": True, "schema": SCHEMA},
    }
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["reasoning_effort"] == "none"
    assert body["reasoning_format"] == "deepseek"
    assert "tools" not in body
    assert completion.output_tokens == 8
    assert completion.first_token_ms is None


def test_completion_only_metadata_does_not_claim_vision_is_unsupported():
    client = ModelClient(
        "http://127.0.0.1:8080/v1",
        "m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": [{"id": "m", "capabilities": ["completion"]}]},
            )
        ),
    )
    assert client.models()[0].vision_supported is None


def test_runtime_props_can_prove_runtime_version_and_vision_capability():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        assert request.url.path == "/props"
        return httpx.Response(
            200,
            json={"build_info": "b10639-2a36554fc", "modalities": {"vision": False}},
        )

    client = ModelClient(
        "http://127.0.0.1:8080/v1", "m", transport=httpx.MockTransport(handler)
    )
    model = client.models()[0]
    assert model.runtime_version == "b10639-2a36554fc"
    assert model.vision_supported is False


def test_input_token_count_uses_chat_template_endpoint():
    def handler(request: httpx.Request):
        assert request.url.path == "/v1/chat/completions/input_tokens"
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "kanıt"
        assert body["model"] == "model-a"
        return httpx.Response(200, json={"input_tokens": 37})

    client = ModelClient(
        "http://127.0.0.1:8080/v1",
        "model-a",
        transport=httpx.MockTransport(handler),
    )
    assert client.count_prompt_tokens([{"role": "user", "content": "kanıt"}]) == 37


def test_length_finish_reason_is_not_accepted():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "length", "message": {"content": "{}"}}
                ]
            },
        )
    )
    client = ModelClient("http://127.0.0.1:8080/v1", "m", transport=transport)
    with pytest.raises(ModelClientError) as exc:
        client.complete([{"role": "user", "content": "x"}], SCHEMA)
    assert exc.value.code == "truncated_output"


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (httpx.ConnectError("offline"), "model_unavailable"),
        (httpx.ReadTimeout("slow"), "model_timeout"),
    ],
)
def test_transport_failures_have_stable_codes(effect, expected):
    def handler(request):
        raise effect

    client = ModelClient(
        "http://127.0.0.1:8080/v1", "m", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ModelClientError) as exc:
        client.models()
    assert exc.value.code == expected


def test_http_error_has_distinct_code():
    client = ModelClient(
        "http://127.0.0.1:8080/v1",
        "m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="not ready")
        ),
    )
    with pytest.raises(ModelClientError) as exc:
        client.models()
    assert exc.value.code == "model_http_error"


def test_sglang_counts_the_same_chat_template_used_for_structured_completion():
    messages = [{"role": "user", "content": "Kanıtı Türkçe özetle."}]
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path == "/v1/tokenize":
            return httpx.Response(200, json={"count": 37, "tokens": [1] * 37})
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"summary":"Kanıt özeti."}'}}],
                "usage": {"prompt_tokens": 37, "completion_tokens": 8},
            })
        return httpx.Response(404)

    client = ModelClient("http://127.0.0.1:30000/v1", "local-qwen", backend="sglang",
                         transport=httpx.MockTransport(handler))
    try:
        assert client.count_prompt_tokens(messages) == 37
        result = client.complete(messages, SCHEMA)
        assert result.text == '{"summary":"Kanıt özeti."}'
        assert result.input_tokens == 37
        assert [path for path, _ in requests] == ["/v1/tokenize", "/v1/chat/completions"]
        for _, body in requests:
            assert body["model"] == "local-qwen"
            assert body["messages"] == messages
            assert body["chat_template_kwargs"] == {"enable_thinking": False}
            assert body["reasoning_effort"] == "none"
            assert "reasoning_format" not in body
        assert requests[1][1]["response_format"]["json_schema"]["schema"] == SCHEMA
    finally:
        client.close()


@pytest.mark.parametrize("count", [None, True, -1, "37", 2.5])
def test_sglang_never_estimates_an_invalid_token_count(count):
    client = ModelClient("http://127.0.0.1:30000/v1", "m", backend="sglang",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"count": count})))
    try:
        with pytest.raises(ModelClientError) as exc:
            client.count_prompt_tokens([{"role": "user", "content": "kanıt"}])
        assert exc.value.code == "token_budget_unverified"
    finally:
        client.close()


def test_sglang_reports_runtime_without_assuming_app_vision_support():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "local-qwen", "owned_by": "sglang"}]})
        assert request.url.path == "/get_server_info"
        return httpx.Response(200, json={"version": "0.5.19"})

    client = ModelClient("http://127.0.0.1:30000/v1", "local-qwen", backend="sglang",
                         transport=httpx.MockTransport(handler))
    try:
        model = client.models()[0]
        assert model.id == "local-qwen"
        assert model.runtime_version == "sglang 0.5.19"
        assert model.vision_supported is None
    finally:
        client.close()


def test_environment_selects_sglang_tokenization_for_both_app_clients(monkeypatch):
    from belgu.analysis import service, assistant

    monkeypatch.setenv("BELGU_MODEL_BACKEND", "sglang")
    monkeypatch.setenv("BELGU_MODEL_URL", "http://127.0.0.1:30000/v1")
    monkeypatch.setenv("BELGU_MODEL_ID", "local-qwen")

    def handler(request):
        if request.url.path == "/v1/tokenize" and json.loads(request.content)["model"] == "local-qwen":
            return httpx.Response(200, json={"count": 37})
        return httpx.Response(404)

    real_client = httpx.Client
    def http_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)
    monkeypatch.setattr(httpx, "Client", http_client)
    for make_client in (service._make_client, assistant._make_client):
        client = make_client()
        try:
            assert client.count_prompt_tokens([{"role": "user", "content": "kanıt"}]) == 37
        finally:
            client.close()


def test_unknown_backend_reports_unavailable_without_contacting_server(monkeypatch):
    from belgu.analysis import service

    monkeypatch.setenv("BELGU_MODEL_BACKEND", "mistyped-backend")
    def unexpected_request(*args, **kwargs):
        raise AssertionError("invalid backend must not contact a model server")
    monkeypatch.setattr(httpx.Client, "request", unexpected_request)
    result = service.get_model_status()
    assert result["status"] == "unavailable"
    assert "backend" in result["message"]
