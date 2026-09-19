"""Regenerate packaged fictional device screenshots offline with real Chromium."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from belgu.core.browser_capture import browser_executable, extract_ocr, _READ_DOCUMENT


def main():
    assets = Path(__file__).resolve().parents[1] / 'src/belgu/demo/assets'
    html = (assets / 'fictional-device.html').read_text()
    manifest = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable(), headless=True)
        try:
            for profile, viewport in [('desktop', {'width': 1365, 'height': 900}), ('mobile', {'width': 390, 'height': 844})]:
                mobile = profile == 'mobile'
                ua = ('Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Mobile Safari/537.36' if mobile else 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36')
                context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile, device_scale_factor=1, user_agent=ua)
                context.route('**/*', lambda route: route.abort())
                page = context.new_page()
                page.set_content(html, wait_until='load')
                png = page.screenshot(full_page=False)
                payload = page.evaluate(_READ_DOCUMENT)
                payload.update(profile=profile, viewport=viewport, is_mobile=mobile, has_touch=mobile,
                    device_scale_factor=1, user_agent=ua, observed_at=datetime.now(timezone.utc).isoformat(),
                    image_sha256=hashlib.sha256(png).hexdigest(), ocr=extract_ocr(png),
                    text_source='recorded_browser_dom', capture_source='packaged_fixture', fixture_version='device-v1')
                (assets / f'fictional-device-{profile}.png').write_bytes(png)
                manifest[profile] = payload
                context.close()
        finally:
            browser.close()
    (assets / 'fictional-device-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Recorded desktop/mobile Chromium screenshots, DOM and local OCR; no network requests.')


if __name__ == '__main__':
    main()
