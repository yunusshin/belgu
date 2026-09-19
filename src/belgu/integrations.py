"""Per-workspace integration settings. Secrets never appear in public views."""
from __future__ import annotations

from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from urllib.parse import urlsplit


LLM_PROVIDERS = {
    'local': {'label': 'Yerel API', 'base_url': 'http://127.0.0.1:8080/v1',
              'docs_url': 'https://docs.sglang.ai/basic_usage/openai_api_completions.html'},
    'anthropic': {'label': 'Claude', 'base_url': 'https://api.anthropic.com/v1',
                  'docs_url': 'https://platform.claude.com/docs/en/api/messages'},
    'openai': {'label': 'OpenAI', 'base_url': 'https://api.openai.com/v1',
               'docs_url': 'https://developers.openai.com/api/reference/resources/responses'},
    'gemini': {'label': 'Gemini', 'base_url': 'https://generativelanguage.googleapis.com/v1beta',
               'docs_url': 'https://ai.google.dev/gemini-api/docs/structured-output'},
    'openrouter': {'label': 'OpenRouter', 'base_url': 'https://openrouter.ai/api/v1',
                   'docs_url': 'https://openrouter.ai/docs/guides/features/structured-outputs'},
}
SOURCE_PROVIDERS = {
    'hackertarget': {'label': 'HackerTarget', 'group': 'reverse', 'accepts_key': True,
                    'description': 'Reverse IP · isteğe bağlı üyelik anahtarı',
                    'docs_url': 'https://hackertarget.com/ip-tools/'},
    'mnemonic': {'label': 'mnemonic PassiveDNS', 'group': 'reverse', 'accepts_key': True,
                 'description': 'Pasif DNS · herkese açık veya API anahtarıyla erişim',
                 'docs_url': 'https://docs.mnemonic.no/service-integration-guides/passivedns/docs/public/01-public_api.html'},
    'urlscan': {'label': 'urlscan.io', 'group': 'intel', 'accepts_key': True,
                'description': 'Mevcut tarama kayıtlarında arama', 'docs_url': 'https://urlscan.io/docs/api/'},
    'threatfox': {'label': 'ThreatFox', 'group': 'intel', 'accepts_key': True,
                  'description': 'abuse.ch IOC sorgusu veya yerel JSON dosyası', 'docs_url': 'https://threatfox.abuse.ch/api/'},
    'crtsh': {'label': 'crt.sh', 'group': 'public', 'accepts_key': False,
              'description': 'Herkese açık sertifika kayıtları', 'docs_url': 'https://crt.sh/'},
    'openphish': {'label': 'OpenPhish Community', 'group': 'public', 'accepts_key': False,
                  'description': 'Herkese açık oltalama akışı · API anahtarı gerekmez',
                  'docs_url': 'https://openphish.com/phishing_feeds.html'},
    'sgb': {'label': 'SGB', 'group': 'local', 'accepts_key': False,
            'description': 'Yerel JSON dosyasından gösterge aktarımı', 'docs_url': None},
}


def defaults() -> dict:
    llm = {}
    for provider, meta in LLM_PROVIDERS.items():
        llm[provider] = {'base_url': meta['base_url'], 'model_id': '',
                         'backend': provider if provider != 'local' else 'llama.cpp',
                         'api_key': os.getenv(f'BELGU_{provider.upper()}_KEY', ''), 'timeout_seconds': 300}
    local = llm['local']
    local.update(base_url=os.getenv('BELGU_MODEL_URL', local['base_url']),
                 model_id=os.getenv('BELGU_MODEL_ID', ''), backend=os.getenv('BELGU_MODEL_BACKEND', 'llama.cpp'),
                 api_key=os.getenv('BELGU_MODEL_KEY', ''))
    try:
        local['timeout_seconds'] = max(1, min(3600, int(os.getenv('BELGU_MODEL_TIMEOUT', '300'))))
    except ValueError:
        pass
    sources = {}
    for name in SOURCE_PROVIDERS:
        key = os.getenv(f'BELGU_{name.upper()}_KEY', '')
        file_path = os.getenv(f'BELGU_{name.upper()}_FILE', '') if name in ('sgb', 'threatfox') else ''
        enabled = (os.getenv('BELGU_OPENPHISH', '0') == '1' if name == 'openphish'
                   else bool(key or file_path) if name in ('sgb', 'threatfox') else True)
        sources[name] = {'enabled': enabled, 'api_key': key, 'file_path': file_path,
                          'mode': 'local' if file_path and not key else 'api'}
    return {'active_llm': 'local', 'llm': llm, 'sources': sources}


def _merge(base, patch):
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _validate_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError('Geçerli bir API adresi girin.')
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        raise ValueError('Geçerli bir API adresi girin.') from None
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('API adresi HTTP/HTTPS olmalı; anahtar, parola veya sorgu içermemeli.')


def _normalize_patch(patch):
    if not isinstance(patch, dict) or set(patch) - {'active_llm', 'llm', 'sources'}:
        raise ValueError('Bilinmeyen ayar alanı.')
    patch = deepcopy(patch)
    if 'active_llm' in patch and patch['active_llm'] not in LLM_PROVIDERS:
        raise ValueError('Geçersiz model sağlayıcısı.')
    for group, catalog in (('llm', LLM_PROVIDERS), ('sources', SOURCE_PROVIDERS)):
        values = patch.get(group, {})
        if not isinstance(values, dict) or set(values) - set(catalog):
            raise ValueError('Bilinmeyen sağlayıcı.')
        for provider, fields in values.items():
            allowed = {'api_key', 'clear_key'}
            if group == 'llm':
                allowed |= {'model_id', 'timeout_seconds'}
                if provider == 'local':
                    allowed |= {'base_url', 'backend'}
            else:
                allowed |= {'enabled'}
                if not catalog[provider]['accepts_key']:
                    allowed -= {'api_key', 'clear_key'}
                if provider in ('sgb', 'threatfox'):
                    allowed |= {'file_path'}
                if provider == 'threatfox':
                    allowed |= {'mode'}
            if not isinstance(fields, dict) or set(fields) - allowed:
                raise ValueError('Sağlayıcı için desteklenmeyen ayar alanı.')
            if 'clear_key' in fields and not isinstance(fields['clear_key'], bool):
                raise ValueError('Anahtar silme seçimi geçersiz.')
            clear = fields.pop('clear_key', False)
            if 'api_key' in fields:
                key = fields['api_key']
                if not isinstance(key, str) or len(key) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in key):
                    raise ValueError('API anahtarı biçimi geçersiz.')
                if key.strip():
                    fields['api_key'] = key.strip()
                else:
                    fields.pop('api_key')  # An empty password input preserves its saved value.
            if clear:
                fields['api_key'] = ''  # Explicitly overrides an environment key as well.
            if 'base_url' in fields:
                _validate_url(fields['base_url'])
                fields['base_url'] = fields['base_url'].rstrip('/')
            if 'backend' in fields and fields['backend'] not in ('llama.cpp', 'sglang', 'openai_compatible'):
                raise ValueError('Yerel API türü geçersiz.')
            if 'model_id' in fields:
                value = fields['model_id']
                if not isinstance(value, str) or len(value) > 200 or any(c.isspace() or ord(c) < 32 for c in value):
                    raise ValueError('Model kimliği geçersiz.')
                if provider == 'gemini':
                    fields['model_id'] = value.removeprefix('models/')
            if 'timeout_seconds' in fields and (type(fields['timeout_seconds']) is not int or not 1 <= fields['timeout_seconds'] <= 3600):
                raise ValueError('Bekleme süresi 1–3600 saniye arasında olmalı.')
            if 'enabled' in fields and not isinstance(fields['enabled'], bool):
                raise ValueError('Kaynak etkinlik seçimi geçersiz.')
            if 'mode' in fields and fields['mode'] not in ('api', 'local'):
                raise ValueError('Kaynak türü geçersiz.')
            if 'file_path' in fields:
                path = fields['file_path']
                if not isinstance(path, str) or len(path) > 2048 or '\x00' in path:
                    raise ValueError('Dosya yolu geçersiz.')
                fields['file_path'] = str(Path(path).expanduser().resolve()) if path else ''
    return patch


class IntegrationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = RLock()

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 256 * 1024:
                raise ValueError()
            value = json.loads(self.path.read_text())
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, ValueError):
            raise ValueError('Bağlantı ayarları okunamadı; kayıtlı dosyayı kontrol edin.') from None

    def snapshot(self, patch=None):
        with self._lock:
            return _merge(_merge(defaults(), self._read()), _normalize_patch(patch or {}))

    def connection(self, snapshot=None):
        config = snapshot if snapshot is not None else self.snapshot()
        return deepcopy(config['llm'][config['active_llm']])

    def configured_connection(self):
        """Keep the established environment-only calling convention until edited."""
        raw = self._read()
        return self.connection() if 'llm' in raw or 'active_llm' in raw else None

    def public(self, snapshot=None):
        config = deepcopy(snapshot if snapshot is not None else self.snapshot())
        for group, catalog in (('llm', LLM_PROVIDERS), ('sources', SOURCE_PROVIDERS)):
            for provider, value in config[group].items():
                value['key_configured'] = bool(value.pop('api_key', ''))
                value.update({key: item for key, item in catalog[provider].items() if key != 'base_url'})
        return config

    def update(self, patch):
        normalized = _normalize_patch(patch)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, 'w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                raw = _merge(self._read(), normalized)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as handle:
                        temporary = handle.name
                        os.chmod(temporary, 0o600)
                        json.dump(raw, handle, ensure_ascii=False, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self.path)
                finally:
                    if temporary and os.path.exists(temporary):
                        os.unlink(temporary)
        return self.public()
