"""Integration management for the single-analyst workspace."""
from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from belgu.analysis.client import ModelClient, ModelClientError
from belgu.analysis.contracts import ModelInfo
from belgu.analysis.service import _resolve_model
from belgu.analysis.budget import input_limit, measure_input
from belgu.core.network import SafeHttpClient
from belgu.core.providers.base import Budget, UpstreamError, ensure_success
from belgu.domain.contracts import Limits
from belgu.integrations import SOURCE_PROVIDERS

Provider = Literal['local', 'anthropic', 'openai', 'gemini', 'openrouter']


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class LlmDraft(Draft):
    api_key: str | None = Field(None, max_length=8192, repr=False)
    clear_key: bool | None = None
    model_id: str | None = Field(None, max_length=200)
    timeout_seconds: int | None = Field(None, ge=1, le=3600)
    base_url: str | None = Field(None, max_length=2048)
    backend: Literal['sglang', 'llama.cpp', 'openai_compatible'] | None = None


class SourceDraft(Draft):
    enabled: bool | None = None
    api_key: str | None = Field(None, max_length=8192, repr=False)
    clear_key: bool | None = None
    file_path: str | None = Field(None, max_length=2048)
    mode: Literal['api', 'local'] | None = None


class IntegrationPatch(Draft):
    active_llm: Provider | None = None
    llm: dict[str, LlmDraft] = Field(default_factory=dict)
    sources: dict[str, SourceDraft] = Field(default_factory=dict)


class LlmView(BaseModel):
    label: str
    docs_url: str
    base_url: str
    backend: str
    model_id: str
    timeout_seconds: int
    key_configured: bool


class SourceView(BaseModel):
    label: str
    group: str
    description: str
    docs_url: str | None
    enabled: bool
    accepts_key: bool
    key_configured: bool
    file_path: str
    mode: str


class IntegrationView(BaseModel):
    active_llm: Provider
    llm: dict[str, LlmView]
    sources: dict[str, SourceView]
    read_only: bool


class LlmCheck(Draft):
    provider: Provider
    settings: LlmDraft = Field(default_factory=LlmDraft)


class SourceCheck(Draft):
    provider: str = Field(max_length=40)
    settings: SourceDraft = Field(default_factory=SourceDraft)


class ConnectionResult(BaseModel):
    status: Literal['ok', 'error']
    message: str
    code: str | None = None
    model_id: str | None = None
    elapsed_ms: int | None = None


class AvailableModels(BaseModel):
    status: Literal['ok', 'error']
    items: list[ModelInfo] = Field(default_factory=list)
    message: str = ''
    code: str | None = None


def _draft(body):
    return body.model_dump(exclude_unset=True, exclude_none=True)


def _probe_source(provider, config):
    if provider == 'sgb' or (provider == 'threatfox' and config['mode'] == 'local'):
        if not config['file_path']:
            raise ValueError('JSON dosyasının tam yolunu girin.')
        path = Path(config['file_path'])
        try:
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('Dosya 20 MiB sınırını aşıyor.')
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            raise ValueError('JSON dosyası okunamadı.') from None
        rows = data if isinstance(data, list) else data.get('data', data.get('models')) if isinstance(data, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Dosya gösterge kayıtlarından oluşan bir JSON listesi içermeli.')
        return f'Dosya okundu: {len(rows)} kayıt.'
    key = config['api_key']
    http = SafeHttpClient(Budget(Limits(max_requests=2, max_seconds=20)))
    try:
        if provider == 'hackertarget':
            response = http.get('https://api.hackertarget.com/reverseiplookup/', params={'q': '1.1.1.1'},
                                headers={'X-API-Key': key} if key else {})
        elif provider == 'mnemonic':
            response = http.get('https://api.mnemonic.no/pdns/v3/example.com', params={'limit': 1},
                                headers={'Argus-API-Key': key} if key else {})
        elif provider == 'urlscan':
            response = (http.get('https://urlscan.io/user/quotas/', headers={'api-key': key}) if key else
                        http.get('https://urlscan.io/api/v1/search/', params={'q': 'page.domain:example.com', 'size': 1}))
        elif provider == 'threatfox':
            if not key:
                raise ValueError('ThreatFox API erişimi için Auth-Key girin.')
            response = http.post('https://threatfox-api.abuse.ch/api/v1/', json_body={'query': 'types'}, headers={'Auth-Key': key})
        elif provider == 'openphish':
            response = http.get('https://openphish.com/feed.txt')
        else:
            response = http.get('https://crt.sh/', params={'q': 'example.com', 'output': 'json'})
        ensure_success(response)
        if provider == 'hackertarget':
            text = response.text.lower()
            if 'api count exceeded' in text or 'rate limit' in text:
                raise UpstreamError('rate_limited', 'upstream_rate_limited')
            if 'error' in text or 'invalid' in text:
                raise ValueError('HackerTarget isteği veya anahtarı kabul etmedi.')
        elif provider == 'threatfox':
            if response.json().get('query_status') != 'ok':
                raise ValueError('ThreatFox API erişimi doğrulanamadı.')
        elif provider != 'openphish':
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError('Beklenen servis yanıtı alınamadı.')
        return 'Bağlantı doğrulandı.'
    finally:
        http.close()


def router(service, settings):
    routes = APIRouter(prefix='/api/settings', tags=['settings'])
    store = service.integrations

    def editable():
        if settings.mode == 'demo':
            raise HTTPException(409, detail='Kayıtlı demo ortamında bağlantı ayarları değiştirilemez veya denenemez.')

    def view():
        return {**store.public(), 'read_only': settings.mode == 'demo'}

    def client_for(body):
        editable()
        config = store.snapshot({'llm': {body.provider: _draft(body.settings)}})
        connection = dict(config['llm'][body.provider])
        connection['timeout_seconds'] = min(connection['timeout_seconds'], 90)
        if body.provider != 'local' and not connection['api_key']:
            raise ValueError('Bu sağlayıcı için API anahtarı girin.')
        return ModelClient(**connection)

    @routes.get('', response_model=IntegrationView)
    def read_settings():
        return view()

    @routes.patch('', response_model=IntegrationView)
    def save_settings(body: IntegrationPatch):
        editable()
        store.update(_draft(body))
        return view()

    @routes.post('/llm/models', response_model=AvailableModels)
    def available_models(body: LlmCheck):
        client = client_for(body)
        try:
            return {'status': 'ok', 'items': client.models()}
        except ModelClientError as exc:
            return {'status': 'error', 'message': str(exc), 'code': exc.code}
        finally:
            client.close()

    @routes.post('/llm/test', response_model=ConnectionResult)
    def test_llm(body: LlmCheck):
        client = client_for(body)
        started = perf_counter()
        try:
            model = _resolve_model(client)
            schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False}
            client.output_schema = schema
            messages = [{'role': 'user', 'content': 'Bağlantı denemesi. Yalnız {"ok":true} JSON yanıtını ver.'}]
            if measure_input(client, messages) > input_limit(client):
                raise ModelClientError('input_budget_exceeded', 'Deneme isteği model bağlamına sığmadı.')
            completion = client.complete(messages, schema, max_output_tokens=128)
            try:
                valid = json.loads(completion.text) == {'ok': True}
            except ValueError:
                valid = False
            if not valid:
                raise ModelClientError('invalid_model_output', 'Bağlantı kuruldu ancak beklenen JSON yanıtı alınamadı.')
            return {'status': 'ok', 'message': 'Bağlantı ve JSON yanıtı doğrulandı.', 'model_id': model.id,
                    'elapsed_ms': int((perf_counter() - started) * 1000)}
        except ModelClientError as exc:
            return {'status': 'error', 'code': exc.code, 'message': str(exc)}
        finally:
            client.close()

    @routes.post('/sources/test', response_model=ConnectionResult)
    def test_source(body: SourceCheck):
        editable()
        if body.provider not in SOURCE_PROVIDERS:
            raise ValueError('Bilinmeyen sağlayıcı.')
        config = store.snapshot({'sources': {body.provider: _draft(body.settings)}})['sources'][body.provider]
        started = perf_counter()
        try:
            message = _probe_source(body.provider, config)
            return {'status': 'ok', 'message': message, 'elapsed_ms': int((perf_counter() - started) * 1000)}
        except UpstreamError as exc:
            message = ('Servisin kota veya istek sınırına ulaşıldı.' if exc.status == 'rate_limited'
                       else 'Servis isteği kabul etmedi. Anahtarı ve erişim yetkisini kontrol edin.')
            return {'status': 'error', 'code': exc.code, 'message': message}
        except ValueError as exc:
            # JSON decoder errors and network errors must not echo upstream content.
            message = 'Beklenen JSON yanıtı alınamadı.' if isinstance(exc, json.JSONDecodeError) else str(exc)
            return {'status': 'error', 'code': 'connection_failed', 'message': message}
        except Exception:
            return {'status': 'error', 'code': 'connection_failed', 'message': 'Servise ulaşılamadı veya yanıt okunamadı.'}

    return routes
