from __future__ import annotations

from time import perf_counter
from typing import Any
from urllib.parse import quote

import httpx

from .contracts import Completion, ModelInfo


class ModelClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ModelClient:
    def __init__(
        self,
        base_url: str,
        model_id: str,
        timeout_seconds: int = 300,
        transport: httpx.BaseTransport | None = None,
        backend: str = "llama.cpp",
        api_key: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self._server_root = (
            self.base_url[: -len("/v1")] if self.base_url.endswith("/v1") else self.base_url
        )
        self.model_id = model_id
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self._has_key = bool(api_key)
        self.output_schema: dict | None = None
        self.budget_kind = 'serialized_bytes' if backend in ('openrouter', 'openai_compatible') else 'tokens'
        headers = {"Accept": "application/json"}
        if backend == 'anthropic':
            headers['anthropic-version'] = '2023-06-01'
        if api_key:
            if backend == 'anthropic':
                headers['x-api-key'] = api_key
            elif backend == 'gemini':
                headers['x-goog-api-key'] = api_key
            else:
                headers['Authorization'] = 'Bearer ' + api_key
        self._http = httpx.Client(
            base_url=self.base_url + "/",
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers=headers,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self.backend not in {"llama.cpp", "sglang", "openai_compatible", "openai", "anthropic", "gemini", "openrouter"}:
            raise ModelClientError(
                "invalid_model_backend", "model backend is not supported"
            )
        if self.backend in ('openai', 'anthropic', 'gemini', 'openrouter') and not self._has_key:
            raise ModelClientError('model_key_required', 'Ayarlar bölümünden bu sağlayıcının API anahtarını ekleyin.')
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ModelClientError("model_timeout", "Model bağlantısı süre sınırını aştı.") from exc
        except httpx.TransportError as exc:
            raise ModelClientError(
                "model_unavailable", "Model sunucusuna ulaşılamadı. API adresini kontrol edin."
            ) from exc
        if response.status_code in (401, 403):
            raise ModelClientError('model_auth_failed', 'API anahtarı veya model erişim yetkisi doğrulanamadı.')
        if response.status_code == 429:
            raise ModelClientError('model_rate_limited', 'Sağlayıcının kota veya istek sınırına ulaşıldı.')
        if response.status_code == 400:
            raise ModelClientError('model_request_rejected', 'Sağlayıcı isteği reddetti (HTTP 400). Modelin JSON şeması desteğini ve bağlam sınırını kontrol edin.')
        if not response.is_success:
            raise ModelClientError(
                "model_http_error",
                f"Model sağlayıcısı HTTP {response.status_code} döndürdü.",
            )
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise ModelClientError(
                "invalid_json_response", "local model returned invalid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise ModelClientError(
                "invalid_json_response", "local model returned a non-object JSON response"
            )
        return data

    def models(self) -> list[ModelInfo]:
        if self.backend in ('anthropic', 'gemini'):
            return self._paginated_models()
        data = self._json(self._request("GET", "models"))
        runtime_version, proven_vision = self._runtime_properties()
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise ModelClientError(
                "invalid_json_response", "model list does not contain a data array"
            )
        result: list[ModelInfo] = []
        for item in raw_models:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            capabilities = item.get("capabilities")
            vision: bool | None = None
            if isinstance(capabilities, list):
                if "vision" in capabilities:
                    vision = True
            runtime = item.get("runtime_version") or runtime_version
            if runtime is not None and not isinstance(runtime, str):
                runtime = None
            result.append(
                ModelInfo(
                    id=item["id"],
                    runtime_version=runtime,
                    text_supported=True,
                    vision_supported=proven_vision if proven_vision is not None else vision,
                )
            )
        if not result:
            raise ModelClientError("no_models", "local endpoint reported no usable models")
        return result

    def _runtime_properties(self) -> tuple[str | None, bool | None]:
        """Read optional backend facts; missing metadata does not block analysis."""
        if self.backend not in ('llama.cpp', 'sglang'):
            return None, None
        path = "/get_server_info" if self.backend == "sglang" else "/props"
        try:
            data = self._json(self._request("GET", self._server_root + path))
        except ModelClientError:
            return None, None
        if self.backend == "sglang":
            version = data.get("version")
            return (f"sglang {version}" if isinstance(version, str) else None), None
        build_info = data.get("build_info")
        if not isinstance(build_info, str):
            build_info = None
        modalities = data.get("modalities")
        vision = modalities.get("vision") if isinstance(modalities, dict) else None
        if not isinstance(vision, bool):
            vision = None
        return build_info, vision

    def count_prompt_tokens(self, messages: list[dict[str, str]]) -> int:
        if self.budget_kind == 'serialized_bytes':
            raise ModelClientError('token_count_unavailable', 'This API does not expose a token counting endpoint.')
        if self.backend in ('openai', 'anthropic', 'gemini'):
            return self._native_count(messages)
        body = {
            "model": self.model_id,
            "messages": messages,
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none",
        }
        # Both endpoints apply the server's chat template to these same messages.
        # Do not estimate by characters or tokenize concatenated message content.
        path = "tokenize" if self.backend == "sglang" else "chat/completions/input_tokens"
        data = self._json(self._request("POST", path, json=body))
        count = data.get("count" if self.backend == "sglang" else "input_tokens")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ModelClientError(
                "token_budget_unverified",
                "local tokenizer did not return a valid input token count",
            )
        return count

    def complete(
        self,
        messages: list[dict[str, str]],
        output_schema: dict,
        max_output_tokens: int = 1024,
    ) -> Completion:
        if max_output_tokens < 1 or max_output_tokens > 1024:
            raise ValueError("max_output_tokens must be between 1 and 1024")
        if self.backend in ('openai', 'anthropic', 'gemini'):
            return self._native_complete(messages, output_schema, max_output_tokens)
        body = {
            "model": self.model_id,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "belgu_analysis",
                    "strict": True,
                    "schema": output_schema,
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none",
        }
        if self.backend == "llama.cpp":
            body["reasoning_format"] = "deepseek"
        if self.backend in ('openrouter', 'openai_compatible'):
            body.pop('chat_template_kwargs')
            body.pop('reasoning_effort')
        if self.backend == 'openrouter':
            body['provider'] = {'require_parameters': True}
            body['response_format']['json_schema']['schema'] = portable_schema(output_schema)
        started = perf_counter()
        data = self._json(self._request("POST", "chat/completions", json=body))
        elapsed_ms = (perf_counter() - started) * 1000
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelClientError(
                "invalid_json_response", "completion response contains no choice"
            )
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise ModelClientError(
                "truncated_output", "local model output reached its token limit"
            )
        if finish_reason not in {"stop", "eos_token"}:
            raise ModelClientError(
                "incomplete_output",
                f"local model did not finish cleanly ({finish_reason!r})",
            )
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelClientError(
                "invalid_json_response", "completion response contains no text"
            )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return Completion(
            text=content,
            finish_reason=finish_reason,
            input_tokens=_optional_int(usage.get("prompt_tokens")),
            output_tokens=_optional_int(usage.get("completion_tokens")),
            first_token_ms=None,
            elapsed_ms=elapsed_ms,
        )

    def _paginated_models(self):
        params: dict = {'limit': 100} if self.backend == 'anthropic' else {'pageSize': 100}
        result = []
        seen = set()
        for _ in range(20):
            data = self._json(self._request('GET', 'models', params=params))
            rows = data.get('data' if self.backend == 'anthropic' else 'models')
            if not isinstance(rows, list):
                raise ModelClientError('invalid_json_response', 'Model listesi okunamadı.')
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if self.backend == 'gemini' and 'generateContent' not in row.get('supportedGenerationMethods', []):
                    continue
                model_id = row.get('id') if self.backend == 'anthropic' else str(row.get('name', '')).removeprefix('models/')
                if isinstance(model_id, str) and model_id and model_id not in seen:
                    seen.add(model_id)
                    result.append(ModelInfo(id=model_id))
            if self.backend == 'anthropic':
                cursor = data.get('last_id') if data.get('has_more') else None
                key = 'after_id'
            else:
                cursor, key = data.get('nextPageToken'), 'pageToken'
            if not cursor:
                break
            if params.get(key) == cursor:
                raise ModelClientError('invalid_json_response', 'Model listesi sayfalaması ilerlemedi.')
            params[key] = cursor
        if not result:
            raise ModelClientError('no_models', 'Sağlayıcı kullanılabilir metin modeli döndürmedi.')
        return result

    def _native_body(self, messages, schema=None):
        if self.backend == 'openai':
            body = {'model': self.model_id, 'input': messages}
            if schema:
                body['text'] = {'format': {'type': 'json_schema', 'name': 'belgu_analysis',
                                           'strict': True, 'schema': portable_schema(schema)}}
            return body
        system = '\n\n'.join(item['content'] for item in messages if item['role'] in ('system', 'developer'))
        conversation = [item for item in messages if item['role'] not in ('system', 'developer')]
        if self.backend == 'anthropic':
            body = {'model': self.model_id, 'messages': conversation}
            if system:
                body['system'] = system
            if schema:
                body['output_config'] = {'format': {'type': 'json_schema', 'schema': portable_schema(schema)}}
            return body
        body = {'contents': [{'role': 'model' if item['role'] == 'assistant' else 'user',
                              'parts': [{'text': item['content']}]} for item in conversation]}
        if system:
            body['systemInstruction'] = {'parts': [{'text': system}]}
        if schema:
            body['generationConfig'] = {'responseMimeType': 'application/json',
                                         'responseJsonSchema': portable_schema(schema)}
        return body

    def _gemini_path(self):
        return 'models/' + quote(self.model_id.removeprefix('models/'), safe='')

    def _native_count(self, messages):
        body = self._native_body(messages, self.output_schema)
        if self.backend == 'openai':
            path, field = 'responses/input_tokens', 'input_tokens'
        elif self.backend == 'anthropic':
            path, field = 'messages/count_tokens', 'input_tokens'
        else:
            path, field = self._gemini_path() + ':countTokens', 'totalTokens'
            body = {'generateContentRequest': {'model': 'models/' + self.model_id.removeprefix('models/'), **body}}
        data = self._json(self._request('POST', path, json=body))
        count = _optional_int(data.get(field))
        if count is None or count < 0:
            raise ModelClientError('token_budget_unverified', 'Sağlayıcı geçerli giriş token sayısı döndürmedi.')
        return count

    def _native_complete(self, messages, schema, max_output_tokens):
        body = self._native_body(messages, schema)
        if self.backend == 'openai':
            path = 'responses'
            body.update(max_output_tokens=max_output_tokens, store=False)
        elif self.backend == 'anthropic':
            path = 'messages'
            body.update(max_tokens=max_output_tokens)
        else:
            path = self._gemini_path() + ':generateContent'
            body['generationConfig']['maxOutputTokens'] = max_output_tokens
        started = perf_counter()
        data = self._json(self._request('POST', path, json=body))
        elapsed_ms = (perf_counter() - started) * 1000
        if self.backend == 'openai':
            status = data.get('status')
            if status != 'completed':
                code = 'truncated_output' if (data.get('incomplete_details') or {}).get('reason') == 'max_output_tokens' else 'incomplete_output'
                raise ModelClientError(code, 'Model yanıtı tamamlanmadı.')
            parts = [part for item in data.get('output', []) if isinstance(item, dict) and item.get('type') == 'message'
                     for part in item.get('content', []) if isinstance(part, dict)]
            texts = [part['text'] for part in parts if part.get('type') == 'output_text' and isinstance(part.get('text'), str)]
            usage = data.get('usage') or {}
            incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
        elif self.backend == 'anthropic':
            if data.get('stop_reason') != 'end_turn':
                code = 'truncated_output' if data.get('stop_reason') == 'max_tokens' else 'incomplete_output'
                raise ModelClientError(code, 'Model yanıtı tamamlanmadı.')
            texts = [part['text'] for part in data.get('content', []) if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str)]
            usage = data.get('usage') or {}
            incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
        else:
            candidates = data.get('candidates') or []
            if not candidates or not isinstance(candidates[0], dict):
                raise ModelClientError('incomplete_output', 'Gemini yanıt üretmedi veya isteği engelledi.')
            choice = candidates[0]
            if choice.get('finishReason') != 'STOP':
                code = 'truncated_output' if choice.get('finishReason') == 'MAX_TOKENS' else 'incomplete_output'
                raise ModelClientError(code, 'Gemini yanıtı tamamlanmadı veya filtrelendi.')
            texts = [part['text'] for part in (choice.get('content') or {}).get('parts', [])
                     if isinstance(part, dict) and not part.get('thought') and isinstance(part.get('text'), str)]
            usage = data.get('usageMetadata') or {}
            incoming, outgoing = usage.get('promptTokenCount'), usage.get('candidatesTokenCount')
        content = '\n'.join(texts)
        if not content.strip():
            raise ModelClientError('invalid_json_response', 'Model metin yanıtı döndürmedi.')
        return Completion(text=content, finish_reason='stop', input_tokens=_optional_int(incoming),
                          output_tokens=_optional_int(outgoing), elapsed_ms=elapsed_ms)


def portable_schema(value):
    """Common structured-output subset; full constraints are still checked locally."""
    if isinstance(value, list):
        return [portable_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    constraints = {key: item for key, item in value.items() if key in (
        'minLength', 'maxLength', 'minItems', 'maxItems', 'minimum', 'maximum', 'pattern', 'format')}
    result = {key: portable_schema(item) for key, item in value.items() if key not in {*constraints, 'default', 'const'}}
    if 'const' in value:
        result['enum'] = [value['const']]
    if constraints:
        result['description'] = (str(result.get('description', '')) + ' Constraints: ' + str(constraints)).strip()
    if result.get('type') == 'object':
        result['additionalProperties'] = False
        result['required'] = list(result.get('properties', {}))
    return result


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
