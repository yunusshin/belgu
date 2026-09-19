import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const demo = process.env.BELGU_DEMO_URL || 'http://127.0.0.1:8775';

test('real API links historical evidence, persists assistant context and compares recorded profiles', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const cases = await (await request.get(`${demo}/api/investigations`)).json();
  const current = cases.items.find((item: any) => item.title === 'Kurgusal mobil bankacılık oltalama kümesi');
  expect(current).toBeTruthy();
  const base = `${demo}/api/investigations/${current.id}`;
  const memory = await (await request.get(base + '/memory')).json();
  const match = memory.items.find((item: any) => item.title === 'Kurgusal önceki marka incelemesi');
  expect(match).toBeTruthy();
  expect(new Set(match.evidence_refs.map((ref: any) => ref.investigation_id)).size).toBe(2);
  await page.goto(`${demo}/#/investigations/${current.id}`);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'İnceleme hafızası', exact: true }).click();
  await expect(page.getByText('Kurgusal önceki marka incelemesi', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Önceki kanıtı aç', exact: true }).first().click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toContainText(
    'Başka incelemenin kanıtı',
  );
  await expect(page.getByRole('button', { name: 'Kanıtı panoya sabitle', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Kanıtı kapat', exact: true }).click();
  await page.screenshot({ path: '../.local/intelligence-v04/memory-desktop.png', fullPage: true });
  await page.getByRole('tab', { name: 'Araştırma asistanı', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Araştırma sorusu', exact: true })
    .fill('Önceki araştırmalarla hangi izler ortak?');
  await page.getByRole('button', { name: 'Sor', exact: true }).click();
  await expect(page.locator('.assistant-answer')).toBeVisible();
  const history = await (await request.get(base + '/assistant')).json();
  const turn = history.items.at(-1);
  expect(turn.model.recorded_demo).toBe(true);
  expect(turn.snapshot.evidence_refs.length).toBeGreaterThan(0);
  for (const claim of turn.claims)
    for (const ref of claim.evidence_refs)
      expect(
        (
          await request.get(`${demo}/api/investigations/${ref.investigation_id}/evidence/${ref.evidence_id}`)
        ).ok(),
      ).toBeTruthy();
  await page.reload();
  await expect(page.locator('.assistant-answer')).toBeVisible();
  await page.getByRole('tab', { name: 'Görsel kanıt', exact: true }).click();
  const captures = await (await request.get(base + '/captures')).json();
  const desktop = captures.items.find(
    (c: any) => c.fixture_version === 'device-v1' && c.profile === 'desktop',
  );
  const mobile = captures.items.find((c: any) => c.fixture_version === 'device-v1' && c.profile === 'mobile');
  expect(desktop).toBeTruthy();
  expect(mobile).toBeTruthy();
  await page.getByRole('button', { name: 'İki gözlem', exact: true }).click();
  await page.getByRole('combobox', { name: 'Görsel kanıt kaydı', exact: true }).selectOption(desktop.id);
  await page.getByRole('combobox', { name: 'İkinci gözlem', exact: true }).selectOption(mobile.id);
  await expect(page.getByAltText('Yakalanan sayfa', { exact: true })).toBeVisible();
  await expect(page.getByAltText('İkinci gözlem', { exact: true })).toBeVisible();
  const dimensions = await page.locator('.image-comparison img').evaluateAll((images) =>
    images.map((img) => {
      const image = img as HTMLImageElement;
      return [image.naturalWidth, image.naturalHeight];
    }),
  );
  expect(dimensions).toContainEqual([1365, 900]);
  expect(dimensions).toContainEqual([390, 844]);
  const ranking = await (await request.get(base + `/visual-similarity?reference_id=${desktop.id}`)).json();
  expect(ranking.unassessed.find((item: any) => item.evidence_id === mobile.id)?.reason).toBe(
    'incompatible_profile',
  );
  await page.screenshot({ path: '../.local/intelligence-v04/profiles-desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('real saved replay exports a masked offline graph with the same events and final decision', async ({
  page,
  request,
  context,
}, testInfo) => {
  const cases = await (await request.get(`${demo}/api/investigations`)).json();
  const current = cases.items.find((item: any) => item.title === 'Kurgusal mobil bankacılık oltalama kümesi');
  await page.goto(`${demo}/#/investigations/${current.id}`);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  const previewResponse = page.waitForResponse(
    (response) => response.url().endsWith('/replay/preview') && response.request().method() === 'POST',
  );
  await page.getByRole('tab', { name: 'Tekrar oynat', exact: true }).click();
  const replay = await (await previewResponse).json();
  expect(replay.recorded).toBe(true);
  expect(replay.events.length).toBeLessThanOrEqual(160);
  expect(replay.events.some((event: any) => event.kind === 'decision')).toBe(true);
  const slider = page.getByRole('slider', { name: 'Kayıtta ara', exact: true });
  await slider.fill(String(replay.events.length - 1));
  await expect(slider).toHaveValue(String(replay.events.length - 1));
  await page.screenshot({ path: '../.local/intelligence-v04/replay-desktop.png', fullPage: true });
  const downloadWait = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Çevrimdışı HTML indir', exact: true }).click();
  const downloaded = await downloadWait;
  expect(downloaded.suggestedFilename()).toMatch(/\.html$/);
  const path = resolve(testInfo.outputPath('replay.html'));
  await downloaded.saveAs(path);
  const html = await readFile(path, 'utf8');
  for (const secret of [current.id, 'guvenli-giris-kuzey.test', '198.51.100.1', 'ada-dogrulama.test'])
    expect(html).not.toContain(secret);
  const offline = await context.newPage();
  const external: string[] = [];
  offline.on('request', (r) => {
    if (/^https?:/.test(r.url())) external.push(r.url());
  });
  await offline.goto(pathToFileURL(path).href);
  await expect(offline.getByRole('button', { name: /Sonraki/ })).toBeVisible();
  const saved = await offline.locator('#replay-data').textContent();
  expect(JSON.parse(saved!).events).toEqual(replay.events);
  await offline.getByRole('button', { name: /Sonraki/ }).click();
  await expect(offline.getByRole('slider', { name: 'Kayıtta ara' })).toHaveValue('1');
  expect(external).toEqual([]);
  await offline.screenshot({ path: '../.local/intelligence-v04/replay-offline.png', fullPage: true });
  await offline.close();
});
