import { test, expect } from '@playwright/test';
const live = 'http://127.0.0.1:8776';
const demo = 'http://127.0.0.1:8775';

test('settings persist private keys, preserve empty passwords, switch sources and clear keys', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${live}/#/settings`);
  await expect(page.getByRole('heading', { name: 'Ayarlar', exact: true })).toBeVisible();
  await expect(page.getByText('Analist çalışma alanı', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Veriler bu cihazda', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'O OpenAI Bulut API' }).click();
  await page.getByLabel('API anahtarı', { exact: false }).fill('fixture-private-key');
  await page.getByLabel('Model kimliği').fill('fixture-model');
  await page.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await expect(page.getByText('Ayarlar kaydedildi. Yeni işlemler bu bağlantılarla çalışacak.')).toBeVisible();
  await expect(page.locator('input[type=password]')).toHaveValue('');
  const result = await request.get(`${live}/api/settings`);
  expect(await result.text()).not.toContain('fixture-private-key');
  expect((await result.json()).llm.openai.key_configured).toBe(true);
  await page.reload();
  await page.getByRole('button', { name: 'O OpenAI Bulut API' }).click();
  await expect(page.getByLabel('Model kimliği')).toHaveValue('fixture-model');
  await expect(page.getByText('Kaydedilmiş', { exact: true })).toBeVisible();
  await page.getByLabel('Yanıt bekleme süresi (sn)').fill('120');
  await page.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await expect(page.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
  expect((await (await request.get(`${live}/api/settings`)).json()).llm.openai.key_configured).toBe(true);
  await page.getByRole('tab', { name: 'Keşif kaynakları' }).click();
  const mnemonic = page.getByRole('article', { name: 'mnemonic PassiveDNS' });
  await mnemonic.getByRole('switch').uncheck();
  await mnemonic.getByLabel('API anahtarı', { exact: false }).fill('fixture-dns-key');
  await page.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await expect(page.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
  const after = (await (await request.get(`${live}/api/settings`)).json()).sources.mnemonic;
  expect(after.enabled).toBe(false);
  expect(after.key_configured).toBe(true);
  await mnemonic.getByRole('button', { name: 'Anahtarı kaldır' }).click();
  await mnemonic.getByRole('switch').check();
  await page.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await expect(page.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
  await page.getByRole('tab', { name: 'Yapay zekâ' }).click();
  await page.getByRole('button', { name: 'Anahtarı kaldır' }).click();
  await page.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await expect(page.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
  expect((await (await request.get(`${live}/api/settings`)).json()).llm.openai.key_configured).toBe(false);
  expect(errors).toEqual([]);
  await page.screenshot({ path: '../.local/validation/settings-desktop.png', fullPage: true });
});

test('demo settings remain read-only and the layout fits a phone', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${demo}/#/settings`);
  await expect(page.getByRole('heading', { name: 'Ayarlar', exact: true })).toBeVisible();
  await expect(page.getByLabel('API adresi')).toBeDisabled();
  expect(
    (await request.post(`${demo}/api/settings/llm/test`, { data: { provider: 'local' } })).status(),
  ).toBe(409);
  await page.getByRole('tab', { name: 'Keşif kaynakları' }).click();
  await expect(page.getByRole('switch').first()).toBeDisabled();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
  await page.screenshot({ path: '../.local/validation/settings-mobile.png', fullPage: true });
});

test('a failed draft probe stays editable and never reports a saved connection', async ({ page }) => {
  await page.goto(`${live}/#/settings`);
  await page.getByLabel('Model kimliği').fill('offline-fixture');
  await page.route('**/api/settings/llm/test', (route) =>
    route.fulfill({
      json: { status: 'error', code: 'model_unavailable', message: 'Model sunucusuna ulaşılamadı.' },
    }),
  );
  await page.getByRole('button', { name: 'Bağlantıyı dene', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Model sunucusuna ulaşılamadı.');
  await expect(page.getByLabel('Model kimliği')).toBeEnabled();
  await expect(page.getByText('Kaydedilmemiş değişiklikler var.')).toBeVisible();
  await page.getByRole('button', { name: 'Vazgeç', exact: true }).click();
});
