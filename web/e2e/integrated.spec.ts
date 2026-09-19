import { test, expect } from '@playwright/test';
const demo = process.env.BELGU_DEMO_URL || 'http://127.0.0.1:8775';
const live = process.env.BELGU_LIVE_URL || 'http://127.0.0.1:8776';
test('real demo: groups, all pages, evidence, attachment, recorded citations and report', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const cases = await (await request.get(`${demo}/api/investigations`)).json();
  const id = cases.items.find((c: any) => c.demo).id;
  await page.goto(`${demo}/#/investigations/${id}`);
  await expect(page.getByTestId('entity-total')).toHaveText('120 alan adı');
  const expectedDomains: string[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams({ kind: 'domain', limit: '100' });
    if (cursor) params.set('cursor', cursor);
    const response = await request.get(`${demo}/api/investigations/${id}/entities?${params}`);
    expect(response.ok()).toBeTruthy();
    const result = await response.json();
    expectedDomains.push(
      ...result.items.map((entity: { canonical_value: string }) => entity.canonical_value),
    );
    cursor = result.next_cursor;
  } while (cursor);
  expect(expectedDomains).toHaveLength(120);
  const values = new Set<string>();
  for (let i = 0; i < 5; i++) {
    await expect(page.locator('.pagination>div>span')).toHaveText(String(i + 1));
    // The page number changes before its request finishes; wait for this page's actual rows.
    await expect(page.locator('.entity-link span')).toHaveText(expectedDomains.slice(i * 25, (i + 1) * 25));
    for (const value of await page.locator('.entity-link span').allTextContents()) {
      expect(values.has(value)).toBeFalsy();
      values.add(value);
    }
    if (i < 4) await page.getByRole('button', { name: 'Sonraki sayfa', exact: true }).click();
  }
  expect(values.size).toBe(120);
  expect([...values]).toEqual(expectedDomains);
  await page.locator('.cluster').first().click();
  await expect(page.getByTestId('entity-total')).toHaveText('30 alan adı');
  await page.locator('.entity-link').first().click();
  const edgeList = page.locator('.research-edge-list');
  if ((await edgeList.getAttribute('open')) === null) await edgeList.locator('summary').click();
  await page.getByRole('button', { name: 'Bağlantının kanıtını aç' }).first().click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
  await expect(page.locator('.evidence-dates')).toContainText('Gözlem zamanı');
  await expect(page.locator('.payload')).not.toBeEmpty();
  await page.getByRole('button', { name: 'Ekran görüntüsünü büyüt' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(
    await page.locator('.attachment-full').evaluate((img: HTMLImageElement) => img.naturalWidth),
  ).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Kapat', exact: true }).click();
  await page.getByRole('button', { name: 'Model analizi', exact: true }).click();
  await expect(page.getByText('Kayıtlı demo yanıtı', { exact: true })).toBeVisible();
  await page.locator('.citation-list button').first().click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Keşfi başlat', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Rapor', exact: true }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Markdown raporu' }).click();
  expect((await downloadPromise).suggestedFilename()).toMatch(/\.md$/);
  expect(errors).toEqual([]);
});
test('real live workspace: create brand and case, preserve full URL, decision and report after reload', async ({
  page,
}) => {
  const title = `Tarayıcı doğrulaması ${Date.now()}`;
  await page.goto(live);
  await page.getByRole('button', { name: 'Yeni inceleme', exact: true }).last().click();
  await page.getByLabel('İnceleme başlığı').fill(title);
  await page.getByRole('button', { name: 'Marka ekle', exact: true }).click();
  await page.getByPlaceholder('Marka adı', { exact: true }).fill('Tarayıcı Test Markası');
  await page.getByPlaceholder('marka.test, marka.com.tr').fill('browser-brand.test');
  await page
    .getByLabel('Tam URL veya alan adı')
    .fill('https://browser-evidence.test/login?ref=analyst&campaign=test');
  await page.getByRole('button', { name: 'İncelemeyi oluştur' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);
  await page.getByRole('button', { name: 'Kayıt ve geçmiş' }).click();
  await expect(page.locator('.submissions-panel')).toContainText(
    'https://browser-evidence.test/login?ref=analyst&campaign=test',
  );
  await page.getByRole('button', { name: 'Karar kaydet', exact: true }).click();
  await page
    .getByLabel('Karar gerekçesi')
    .fill('Tarayıcı doğrulaması: kurmaca alan adı, ek gözlem bekleniyor.');
  await page.getByRole('button', { name: 'Kararı kaydet', exact: true }).click();
  await expect(page.locator('.timeline')).toContainText('Tarayıcı doğrulaması: kurmaca alan adı');
  await page.reload();
  await page.getByRole('button', { name: 'Kayıt ve geçmiş' }).click();
  await expect(page.locator('.timeline')).toContainText('Tarayıcı doğrulaması: kurmaca alan adı');
  await page.getByRole('button', { name: 'Rapor', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'JSON verisi' }).click();
  expect((await download).suggestedFilename()).toMatch(/\.json$/);
});
for (const width of [390, 1024, 1440, 1920]) {
  test(`responsive dark/light workspace at ${width}px`, async ({ page, request }) => {
    const cases = await (await request.get(`${demo}/api/investigations`)).json();
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${demo}/#/investigations/${cases.items.find((c: any) => c.demo).id}`);
    await expect(page.getByTestId('entity-total')).toHaveText('120 alan adı');
    for (const theme of ['dark', 'light']) {
      if (theme === 'light') await page.getByRole('button', { name: 'Açık temaya geç' }).click();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(overflow).toBeFalsy();
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({
        path: `test-results/integrated-${theme}-${width}.png`,
        fullPage: true,
        animations: 'disabled',
      });
    }
  });
}
