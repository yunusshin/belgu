import { test, expect, type Page, type Locator } from '@playwright/test';
import { installApiFixtures } from './fixtures';

async function raster(page: Page, width: number, height: number, title: string) {
  const data = await page.evaluate(
    ({ width, height, title }) => {
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d')!;
      context.fillStyle = '#ecf7f2';
      context.fillRect(0, 0, width, height);
      context.fillStyle = '#0b554a';
      context.fillRect(0, 0, width, height * 0.16);
      context.fillStyle = '#ffffff';
      context.font = 'bold 32px sans-serif';
      context.fillText(title, width * 0.07, height * 0.1);
      context.fillStyle = '#70cbb4';
      context.fillRect(width * 0.2, height * 0.2, width * 0.4, height * 0.4);
      context.fillStyle = '#244d47';
      context.fillRect(width * 0.25, height * 0.3, width * 0.3, height * 0.07);
      context.fillRect(width * 0.25, height * 0.43, width * 0.3, height * 0.07);
      context.fillStyle = '#cb956d';
      context.fillRect(width * 0.72, height * 0.7, width * 0.15, height * 0.12);
      return canvas.toDataURL('image/png').split(',')[1];
    },
    { width, height, title },
  );
  return Buffer.from(data, 'base64');
}

async function comparison(page: Page, options: { reference?: 'ready' | 'missing' | 'failed' } = {}) {
  await installApiFixtures(page, { demo: false });
  const capturePng = await raster(page, 1200, 800, 'Captured fixture page');
  const referencePng = await raster(page, 900, 900, 'Analyst reference');
  let failReference = options.reference === 'failed';
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/comparison-capture.png')
      return route.fulfill({ contentType: 'image/png', body: capturePng });
    if (path === '/api/comparison-reference.png')
      return failReference
        ? route.fulfill({ status: 404, body: 'Image unavailable' })
        : route.fulfill({ contentType: 'image/png', body: referencePng });
    if (path.endsWith('/captures'))
      return route.fulfill({
        json: {
          items: [
            {
              id: 'capture-1',
              evidence_id: 'ev-1',
              artifact_id: 'image-1',
              image_url: '/api/comparison-capture.png',
              url: 'https://giris-01.test/login',
              final_url: 'https://giris-01.test/login',
              observed_at: '2026-09-10T10:00:00Z',
              text: 'DOM fixture text',
              ocr_text: 'OCR fixture text',
              ocr_status: 'ok',
              forms: [{ method: 'post', action: '/login', inputs: [{ name: 'password', type: 'password' }] }],
              status_code: 200,
            },
          ],
          references:
            options.reference === 'missing'
              ? []
              : [
                  {
                    id: 'reference-1',
                    image_url: '/api/comparison-reference.png',
                    created_at: '2026-09-10T09:00:00Z',
                  },
                ],
          capabilities: { status: 'ready', message: 'Tarayıcı hazır.', ocr_available: true },
        },
      });
    if (path.endsWith('/candidates'))
      return route.fulfill({ json: { items: [], total_unique: 0, next_cursor: null } });
    return route.fallback();
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  return {
    recover: () => {
      failReference = false;
    },
  };
}

async function box(locator: Locator) {
  const bounds = await locator.boundingBox();
  expect(bounds).not.toBeNull();
  return bounds!;
}

test('real images keep aspect ratios while zoom, pan and overlay divider stay synchronized', async ({
  page,
}) => {
  await comparison(page);
  await expect(page.getByText('1200 × 800 px', { exact: true })).toBeVisible();
  await expect(page.getByText('900 × 900 px', { exact: true })).toBeVisible();
  await expect(page.getByText(/En-boy oranları farklı/)).toBeVisible();
  const capture = page.getByAltText('Yakalanan sayfa', { exact: true });
  const reference = page.getByAltText('Marka referansı', { exact: true });
  const original = await box(capture);
  expect(original.width / original.height).toBeCloseTo(1.5, 2);
  const zoom = page.getByRole('slider', { name: 'Birlikte yakınlaştır', exact: true });
  await zoom.focus();
  for (let n = 0; n < 4; n++) await zoom.press('ArrowRight');
  await expect(zoom).toHaveValue('200');
  await page.getByTestId('comparison-capture-pane').scrollIntoViewIfNeeded();
  const beforeCapture = await box(capture),
    beforeReference = await box(reference);
  expect(beforeCapture.width / original.width).toBeCloseTo(2, 2);
  const pane = await box(page.getByTestId('comparison-capture-pane'));
  await page.mouse.move(pane.x + pane.width / 2, pane.y + pane.height / 2);
  await page.mouse.down();
  await page.mouse.move(pane.x + pane.width / 2 + 45, pane.y + pane.height / 2 + 20, { steps: 5 });
  await page.mouse.up();
  const afterCapture = await box(capture),
    afterReference = await box(reference);
  expect(afterCapture.x - beforeCapture.x).toBeGreaterThan(30);
  expect((afterCapture.x - beforeCapture.x) / afterCapture.width).toBeCloseTo(
    (afterReference.x - beforeReference.x) / afterReference.width,
    2,
  );
  expect((afterCapture.y - beforeCapture.y) / afterCapture.height).toBeCloseTo(
    (afterReference.y - beforeReference.y) / afterReference.height,
    2,
  );
  await page.getByRole('button', { name: 'Üst üste', exact: true }).click();
  const divider = page.getByRole('slider', { name: 'Karşılaştırma ayırıcı', exact: true });
  await divider.focus();
  await divider.press('ArrowRight');
  await expect(divider).toHaveValue('51');
  await page.getByTestId('comparison-overlay-pane').scrollIntoViewIfNeeded();
  const overlay = await box(page.getByTestId('comparison-overlay-pane'));
  const handle = await box(page.getByTestId('comparison-divider'));
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(overlay.x + overlay.width * 0.7, overlay.y + overlay.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(Number(await divider.inputValue())).toBeGreaterThanOrEqual(68);
  expect(Number(await divider.inputValue())).toBeLessThanOrEqual(72);
  await page.getByRole('button', { name: 'Görünümü sıfırla', exact: true }).click();
  await expect(zoom).toHaveValue('100');
  await expect(divider).toHaveValue('50');
  await expect(page.getByText('OCR fixture text', { exact: true })).toBeVisible();
  await expect(page.getByText('password', { exact: true }).first()).toBeVisible();
});

test('a dragged rectangle focuses the same normalized region and survives tool navigation', async ({
  page,
}) => {
  await comparison(page);
  await expect(page.getByText('1200 × 800 px', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Alan seç', exact: true }).click();
  await page.getByTestId('comparison-capture-pane').scrollIntoViewIfNeeded();
  const capture = page.getByAltText('Yakalanan sayfa', { exact: true });
  const bounds = await box(capture);
  await page.mouse.move(bounds.x + bounds.width * 0.2, bounds.y + bounds.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.6, bounds.y + bounds.height * 0.6, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByRole('slider', { name: 'Birlikte yakınlaştır', exact: true })).toHaveValue('250');
  const captureRect = await box(capture),
    referenceRect = await box(page.getByAltText('Marka referansı', { exact: true }));
  const capturePane = await box(page.getByTestId('comparison-capture-pane'));
  const referencePane = await box(page.getByTestId('comparison-reference-pane'));
  expect((capturePane.x + capturePane.width / 2 - captureRect.x) / captureRect.width).toBeCloseTo(0.4, 1);
  expect((referencePane.x + referencePane.width / 2 - referenceRect.x) / referenceRect.width).toBeCloseTo(
    0.4,
    1,
  );
  expect((await box(page.getByTestId('comparison-capture-selection'))).width / captureRect.width).toBeCloseTo(
    0.4,
    1,
  );
  expect(
    (await box(page.getByTestId('comparison-reference-selection'))).width / referenceRect.width,
  ).toBeCloseTo(0.4, 1);
  await page.getByRole('tab', { name: 'Adaylar', exact: true }).click();
  await page.getByRole('tab', { name: 'Görsel kanıt', exact: true }).click();
  await expect(page.getByRole('slider', { name: 'Birlikte yakınlaştır', exact: true })).toHaveValue('250');
  await expect(page.getByTestId('comparison-capture-selection')).toBeVisible();
});

test('missing and failed references stay explicit without hiding the actual capture', async ({ page }) => {
  await comparison(page, { reference: 'missing' });
  await expect(page.getByAltText('Yakalanan sayfa', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Üst üste', exact: true })).toBeDisabled();
  await expect(page.getByText('Referans görüntüsü seçilmedi.', { exact: true })).toBeVisible();
});

test('a failed image can be retried and enables comparison only after loading', async ({ page }) => {
  const fixture = await comparison(page, { reference: 'failed' });
  await expect(page.getByText('Marka referansı yüklenemedi.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Üst üste', exact: true })).toBeDisabled();
  fixture.recover();
  await page.getByRole('button', { name: 'Marka referansı görüntüsünü yeniden yükle' }).click();
  await expect(page.getByText('900 × 900 px', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Üst üste', exact: true })).toBeEnabled();
});

for (const width of [390, 1440])
  for (const theme of ['dark', 'light']) {
    test(`comparison controls and real images fit ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((theme) => localStorage.setItem('belgu-theme', theme), theme);
      await comparison(page);
      await expect(page.getByText('1200 × 800 px', { exact: true })).toBeVisible();
      await page
        .getByRole('region', { name: 'Görsel karşılaştırma', exact: true })
        .screenshot({ path: testInfo.outputPath(`comparison-split-${width}-${theme}.png`) });
      await page.getByRole('button', { name: 'Üst üste', exact: true }).click();
      await expect(page.getByTestId('comparison-overlay-pane')).toBeVisible();
      const panel = await box(page.getByRole('region', { name: 'Görsel karşılaştırma', exact: true }));
      expect(panel.x).toBeGreaterThanOrEqual(0);
      expect(panel.x + panel.width).toBeLessThanOrEqual(width + 1);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      expect(overflow).toBe(false);
      await page
        .getByRole('region', { name: 'Görsel karşılaştırma', exact: true })
        .screenshot({ path: testInfo.outputPath(`comparison-${width}-${theme}.png`) });
    });
  }
