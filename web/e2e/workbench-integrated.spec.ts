import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const live = process.env.BELGU_LIVE_URL || 'http://127.0.0.1:8776';
const image = fileURLToPath(new URL('../../src/belgu/demo/assets/fictional-login.png', import.meta.url));
test('real workbench API: capture evidence, reference upload, candidates, run changes, watches and masked HTML', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const cases = await (await request.get(`${live}/api/investigations`)).json();
  const inv = cases.items.find((item: any) => item.title === 'Çalışma masası tarayıcı doğrulaması');
  expect(inv, 'isolated workbench browser fixture').toBeTruthy();
  const base = `${live}/api/investigations/${inv.id}`;
  await page.goto(`${live}/#/investigations/${inv.id}`);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await expect(page.getByAltText('Yakalanan sayfa')).toBeVisible();
  expect(
    await page.getByAltText('Yakalanan sayfa').evaluate((img: HTMLImageElement) => img.naturalWidth),
  ).toBeGreaterThan(100);
  await expect(page.getByText('parola', { exact: true })).toBeVisible();
  await page.getByLabel('Marka referansı yükle').setInputFiles(image);
  await expect(page.getByAltText('Marka referansı')).toBeVisible();
  expect((await (await request.get(base + '/captures')).json()).references.length).toBeGreaterThan(0);
  await page.screenshot({ path: 'test-results/workbench-visual-dark.png', fullPage: true });
  await page.getByRole('tab', { name: 'Adaylar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'related-browser.test', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Başlangıç bulgusu yap', exact: true }).click();
  await expect
    .poll(async () =>
      (await (await request.get(base)).json()).submissions.some(
        (s: any) => s.target.hostname === 'related-browser.test',
      ),
    )
    .toBeTruthy();
  await page.getByRole('tab', { name: 'Değişimler', exact: true }).click();
  await expect(page.locator('.desk-before-after')).toContainText('198.51.100.21');
  await expect(page.locator('.desk-before-after')).toContainText('198.51.100.22');
  await page.getByRole('tab', { name: 'İzleme', exact: true }).click();
  await page.getByRole('button', { name: 'Etkinleştir', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Duraklat', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Duraklat', exact: true }).click();
  await page.getByRole('button', { name: 'Okundu olarak işaretle', exact: true }).click();
  await expect(page.getByText('Okundu', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Paylaşım', exact: true }).click();
  await page.getByLabel('Kanıtı seç: browser_capture · https://browser-workbench.test/login').check();
  await page.getByRole('button', { name: 'Önizlemeyi oluştur', exact: true }).click();
  const preview = page.getByRole('region', { name: 'Sunum önizlemesi' });
  await expect(preview).toContainText('Maskelenmiş');
  await page.getByRole('button', { name: 'Sonraki kart', exact: true }).click();
  await expect(preview).toContainText('Görsel kanıt');
  await expect(preview).not.toContainText('browser-workbench.test');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'HTML sunumunu indir', exact: true }).click();
  const download = await downloadPromise,
    path = await download.path();
  const html = await readFile(path!, 'utf8');
  for (const secret of [
    'browser-workbench.test',
    'related-browser.test',
    '198.51.100.21',
    inv.id,
    'data:image',
  ])
    expect(html).not.toContain(secret);
  expect(html).toContain('Sonraki');
  await page.screenshot({ path: 'test-results/workbench-story-dark.png', fullPage: true });
  await page.getByLabel('Kimlikleri maskele', { exact: true }).uncheck();
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'HTML sunumunu indir', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Önizlemeyi oluştur', exact: true }).click();
  await page.getByRole('button', { name: 'Sonraki kart', exact: true }).click();
  await expect(preview).toContainText('browser-workbench.test');
  await expect(preview.getByAltText('Seçili kanıtın görüntüsü')).toBeVisible();
  await page.getByRole('button', { name: 'Model analizi', exact: true }).click();
  await page.getByText('Kaynak alanları ve zamanları', { exact: false }).first().click();
  await expect(page.locator('.grounding-fields').first()).toContainText('credential_form');
  await expect(page.locator('.grounding-times').first()).toContainText('Gözlem zamanı');
  await expect(page.getByText('Atıf bu incelemede bulunamadı.', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

for (const width of [390, 1440]) {
  test(`real workbench stays usable in dark and light at ${width}px`, async ({ page, request }) => {
    const cases = await (await request.get(`${live}/api/investigations`)).json();
    const inv = cases.items.find((item: any) => item.title === 'Çalışma masası tarayıcı doğrulaması');
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${live}/#/investigations/${inv.id}`);
    await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
    for (const theme of ['dark', 'light']) {
      if (theme === 'light') await page.getByRole('button', { name: 'Açık temaya geç' }).click();
      for (const [tab, name] of [
        ['Görsel kanıt', 'visual'],
        ['Adaylar', 'candidates'],
        ['Değişimler', 'changes'],
        ['İzleme', 'watches'],
        ['Paylaşım', 'story'],
      ]) {
        await page.getByRole('tab', { name: tab, exact: true }).click();
        await expect(page.getByRole('tabpanel')).toBeVisible();
        await expect(page.locator('.workbench .loading')).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBeFalsy();
        if (name === 'visual' || name === 'story')
          await page.screenshot({
            path: `test-results/workbench-${name}-${theme}-${width}.png`,
            fullPage: true,
          });
      }
    }
  });
}
