"""Bounded Chromium rendering with all remote reads delegated to SafeHttpClient."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urldefrag, urlsplit

from belgu.core.network import FetchLimitExceeded, NetworkPolicyError, SafeHttpClient
from belgu.core.providers.base import Budget
from belgu.domain.contracts import Limits


CAPTURE_LIMITS = Limits(max_requests=40, max_seconds=45, provider_concurrency=1)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
VIEWPORT = {"width": 1365, "height": 900}
_USER_AGENTS = {
    'desktop': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
    'mobile': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36',
}


def profile_settings(profile='desktop'):
    if profile not in _USER_AGENTS:
        raise ValueError('Capture profile must be desktop or mobile')
    return {'profile': profile, 'viewport': dict(VIEWPORT) if profile == 'desktop' else {'width': 390, 'height': 844},
            'user_agent': _USER_AGENTS[profile], 'device_scale_factor': 1,
            'is_mobile': profile == 'mobile', 'has_touch': profile == 'mobile'}


def observation_profile(payload):
    """A legacy desktop assumption is explicit; its unknown UA is never invented."""
    legacy = not payload.get('profile')
    settings = profile_settings(payload.get('profile', 'desktop'))
    return {**settings, **{k: payload[k] for k in settings if k in payload},
            'user_agent': payload.get('user_agent'), 'legacy_profile': legacy,
            'profile_label': 'Masaüstü · eski kayıt (ayarlar bilinmiyor)' if legacy else
                ('Mobil' if payload['profile'] == 'mobile' else 'Masaüstü')}



class CaptureUnavailable(RuntimeError):
    pass


class CaptureCancelled(RuntimeError):
    pass


def browser_executable() -> str | None:
    configured = os.environ.get('BELGU_CHROMIUM_PATH')
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    cache = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', Path.home() / '.cache/ms-playwright')).expanduser()
    candidates = [*cache.glob('chromium-*/chrome-linux/chrome'),
                  *cache.glob('chromium-*/chrome-linux64/chrome'),
                  *cache.glob('chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium')]
    for candidate in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return next((value for name in ('chromium', 'chromium-browser', 'google-chrome')
                 if (value := shutil.which(name))), None)


def ocr_executable() -> str | None:
    configured = os.environ.get('BELGU_TESSERACT_PATH')
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    installed = shutil.which('tesseract')
    if installed:
        return installed
    candidates = (Path(__file__).resolve().parents[3] / '.local/bin/tesseract',
                  Path.cwd() / '.local/bin/tesseract')
    return next((str(path) for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


def capabilities() -> dict:
    browser = bool(importlib.util.find_spec('playwright')) and bool(browser_executable())
    ocr = bool(ocr_executable())
    return {
        'status': 'ready' if browser else 'unavailable',
        'browser_available': browser,
        'ocr_available': ocr,
        'message': ('Chromium hazır; yerel OCR ' + ('hazır.' if ocr else 'kurulu değil.'))
            if browser else 'Görsel yakalama için Python Playwright ve Chromium kurulmalıdır.',
        'limits': {'max_requests': CAPTURE_LIMITS.max_requests,
                   'max_seconds': CAPTURE_LIMITS.max_seconds,
                   'max_response_bytes': MAX_RESPONSE_BYTES,
                   'max_total_bytes': MAX_TOTAL_BYTES,
                   'viewport': dict(VIEWPORT)},
    }


def extract_ocr(png: bytes, *, cancelled=None) -> dict:
    """OCR reads the captured PNG locally; it never receives DOM text."""
    executable = ocr_executable()
    default_languages = 'tur+eng' if executable and executable.endswith('/.local/bin/tesseract') else 'eng'
    result = {'engine': 'tesseract', 'source': 'screenshot', 'status': 'unavailable',
              'text': '', 'languages': os.environ.get('BELGU_OCR_LANG', default_languages),
              'limitations': ['OCR karakterleri yanlış okuyabilir; görüntüyle doğrulayın.']}
    if cancelled and cancelled():
        return {**result, 'status': 'cancelled'}
    if not executable:
        return {**result, 'error': 'tesseract_not_installed'}
    try:
        completed = subprocess.run(
            [executable, 'stdin', 'stdout', '-l', result['languages'], '--psm', '11'],
            input=png, capture_output=True, timeout=10, check=False,
            env={**os.environ, 'OMP_THREAD_LIMIT': '1'},
        )
        if completed.returncode:
            return {**result, 'status': 'error', 'error': completed.stderr.decode('utf-8', errors='replace')[:500]
                    or f'tesseract_exit_{completed.returncode}'}
        text = completed.stdout.decode('utf-8', errors='replace').strip()
        return {**result, 'status': 'ok' if text else 'empty', 'text': text[:12000],
                'truncated': len(text) > 12000}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**result, 'status': 'error', 'error': type(exc).__name__}


# Navigation interception also rejects form-driven GETs. These guards prevent the
# usual submission APIs before scripts run; no clicks, filling or interaction occur.
_READ_ONLY_SCRIPT = """(() => {
  addEventListener('submit', event => { event.preventDefault(); event.stopImmediatePropagation(); }, true);
  for (const name of ['submit', 'requestSubmit']) {
    Object.defineProperty(HTMLFormElement.prototype, name, {
      configurable: false, writable: false, value: function () {}
    });
  }
  window.open = () => null;
})()"""

_READ_DOCUMENT = """() => {
  const trim = value => String(value || '').slice(0, 500);
  const input = node => {
    const box = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return {tag: node.tagName.toLowerCase(), type: trim(node.type || node.tagName.toLowerCase()),
      name: trim(node.name), id: trim(node.id), placeholder: trim(node.placeholder),
      autocomplete: trim(node.autocomplete), required: !!node.required,
      disabled: !!node.disabled, visible: box.width > 0 && box.height > 0 &&
        style.visibility !== 'hidden' && style.display !== 'none'};
  };
  const allInputs = Array.from(document.querySelectorAll('input,select,textarea,button'));
  const allForms = Array.from(document.forms);
  const text = document.body ? document.body.innerText : '';
  return {title: document.title.slice(0, 300), text: text.slice(0, 12000),
    forms: allForms.slice(0, 20).map(form => ({
      action: trim(form.action), method: trim(form.method).toLowerCase(),
      inputs: Array.from(form.elements).slice(0, 100).map(input)})),
    inputs: allInputs.slice(0, 200).map(input),
    credential_form: allInputs.some(node => node.tagName === 'INPUT' && node.type === 'password'),
    text_truncated: text.length > 12000,
    forms_truncated: allForms.length > 20 || allForms.some(form => form.elements.length > 100),
    inputs_truncated: allInputs.length > 200};
}"""


async def _render(response, http, budget, *, cancelled, progress, profile):
    from playwright.async_api import async_playwright

    def check():
        if cancelled and cancelled():
            raise CaptureCancelled('Görsel yakalama iptal edildi.')
        if not budget.remaining_seconds():
            raise FetchLimitExceeded('Görsel yakalama süresi doldu.')

    failed_requests, blocked_requests = [], []
    total_bytes = len(response.body)
    initial_served = False
    read_lock = asyncio.Lock()
    clean_url = lambda value: urldefrag(value)[0]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=browser_executable(), headless=True,
            timeout=min(10000, max(1, budget.remaining_seconds() * 1000)),
            args=['--disable-background-networking', '--disable-component-update', '--disable-sync',
                  '--no-pings', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],
        )
        try:
            settings = profile_settings(profile)
            context = await browser.new_context(**{k: v for k, v in settings.items() if k != 'profile'},
                service_workers='block', accept_downloads=False, java_script_enabled=True)
            await context.add_init_script(_READ_ONLY_SCRIPT)
            await context.route_web_socket('**/*', lambda socket: socket.close())
            page = await context.new_page()
            page.set_default_timeout(8000)

            async def route_request(route):
                nonlocal initial_served, total_bytes
                request = route.request
                initial = (not initial_served and request.is_navigation_request()
                           and request.frame == page.main_frame
                           and clean_url(request.url) == clean_url(response.url))
                reason = None
                if request.method != 'GET' or request.post_data:
                    reason = 'non_get_or_submission'
                elif urlsplit(request.url).scheme not in ('http', 'https'):
                    reason = 'non_http'
                elif request.is_navigation_request() and not initial:
                    reason = 'navigation_or_frame_blocked'
                elif request.resource_type not in {'document', 'stylesheet', 'script', 'image', 'font'}:
                    reason = 'non_visual_request_blocked'
                if reason:
                    if len(blocked_requests) < 50:
                        blocked_requests.append({'url': request.url[:2000], 'reason': reason})
                    await route.abort()
                    return
                try:
                    check()
                    if initial:
                        initial_served = True
                        fetched = response
                    else:
                        async with read_lock:
                            check()
                            remaining_bytes = MAX_TOTAL_BYTES - total_bytes
                            if remaining_bytes <= 0:
                                raise FetchLimitExceeded('Toplam yanıt boyutu sınırı doldu.')
                            http.max_bytes = min(MAX_RESPONSE_BYTES, remaining_bytes)
                            fetched = await asyncio.to_thread(http.get, request.url, headers={'User-Agent': settings['user_agent']})
                            total_bytes += len(fetched.body)
                    if fetched.status_code >= 400 and len(failed_requests) < 50:
                        failed_requests.append({'url': request.url[:2000],
                            'error_type': 'HttpStatusError', 'status_code': fetched.status_code,
                            'reason': f'HTTP {fetched.status_code}'})
                    # SafeHttpClient decompresses the body; stale transport headers
                    # must not ask Chromium to decompress those bytes a second time.
                    headers = {key: value for key, value in fetched.headers.items()
                               if key.lower() not in {'content-encoding', 'content-length',
                                   'transfer-encoding', 'connection', 'set-cookie',
                                   'content-disposition', 'refresh'}}
                    await route.fulfill(status=fetched.status_code, headers=headers, body=fetched.body)
                    if progress:
                        progress({**budget.snapshot(), 'message': 'Sayfa görseli hazırlanıyor'})
                except Exception as exc:
                    if len(failed_requests) < 50:
                        failed_requests.append({'url': request.url[:2000],
                                                'error_type': type(exc).__name__, 'reason': str(exc)[:500]})
                    await route.abort()

            await context.route('**/*', route_request)
            check()
            await page.goto(response.url, wait_until='domcontentloaded',
                            timeout=max(1, budget.remaining_seconds() * 1000))
            # A short bounded settle permits ordinary scripts to update the DOM;
            # there is deliberately no unbounded network-idle wait.
            await page.wait_for_timeout(min(700, max(1, budget.remaining_seconds() * 1000)))
            check()
            document = await page.evaluate(_READ_DOCUMENT)
            png = await page.screenshot(type='png', full_page=False, animations='disabled',
                timeout=min(8000, max(1, budget.remaining_seconds() * 1000)))
            observed_at = datetime.now(timezone.utc)
            check()
            document.update({'requested_url': response.redirects[0] if response.redirects else response.url,
                'url': response.url, 'final_url': page.url, 'status_code': response.status_code,
                'redirects': list(response.redirects), 'text_source': 'rendered_dom',
                'observed_at': observed_at.isoformat(), **settings,
                'requests': budget.requests, 'bytes': total_bytes,
                'failed_requests': failed_requests, 'blocked_requests': blocked_requests,
                'limitations': [
                    'Görüntü seçilen profilin tek görünüm alanını gösterir; aşağıdaki içerik görüntü dışında kalabilir.',
                    'Metin ve alanlar üst belgenin DOM yapısından alınır; iframe ve kapalı gölge kökleri kapsanmaz.',
                    'Form gönderimleri, ek gezinmeler, WebSocket, fetch/XHR ve diğer görsel olmayan istekler engellenir; sayfa eksik görünebilir.',
                    'Hiçbir giriş alanı doldurulmadı; form gönderilmedi.',
                    'Mevcut model yalnız metin işler; görüntü üzerinde model yorumu yapılmadı.',
                ]})
            return png, document, observed_at
        finally:
            await browser.close()


async def _bounded_render(response, http, budget, *, cancelled, progress, profile):
    rendering = asyncio.create_task(_render(response, http, budget, cancelled=cancelled, progress=progress, profile=profile))
    try:
        while not rendering.done():
            if cancelled and cancelled():
                raise CaptureCancelled('Görsel yakalama iptal edildi.')
            if not budget.remaining_seconds():
                raise FetchLimitExceeded('Görsel yakalama süresi doldu.')
            await asyncio.wait({rendering}, timeout=min(.2, budget.remaining_seconds()))
        return await rendering
    finally:
        if not rendering.done():
            rendering.cancel()
        await asyncio.gather(rendering, return_exceptions=True)


def capture_browser(url: str, *, budget: Budget, cancelled=None, progress=None, profile='desktop'):
    settings = profile_settings(profile)
    if cancelled and cancelled():
        raise CaptureCancelled('Görsel yakalama iptal edildi.')
    if not capabilities()['browser_available']:
        raise CaptureUnavailable('Python Playwright veya Chromium bulunamadı.')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None:
        raise NetworkPolicyError('Kimlik bilgisi içermeyen HTTP veya HTTPS adresi gerekli.')
    http = SafeHttpClient(budget, max_bytes=MAX_RESPONSE_BYTES)
    try:
        response = http.get(url, headers={'User-Agent': settings['user_agent']})
        if progress:
            progress({**budget.snapshot(), 'message': 'Chromium ile sayfa açılıyor'})
        png, payload, observed_at = asyncio.run(_bounded_render(response, http, budget,
            cancelled=cancelled, progress=progress, profile=profile))
        payload['url'] = payload['requested_url'] = url
        return png, payload, observed_at
    finally:
        http.close()
