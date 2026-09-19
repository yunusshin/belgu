import { expect, test, type Page } from '@playwright/test';
import { installApiFixtures } from './fixtures';

async function unifiedFixtures(page: Page) {
  const { caseData } = await installApiFixtures(page);
  const records = [
    {
      id: 'ev-1',
      kind: 'page_content',
      provider: 'page',
      subject: { kind: 'domain', value: 'first-private.test' },
      source_ref: 'https://first-private.test',
      observed_at: '2026-09-09T12:00:00Z',
      retrieved_at: '2026-09-09T12:01:00Z',
      payload: { text: 'İlk sayfa gözlemi' },
    },
    {
      id: 'ev-2',
      kind: 'dns_a',
      provider: 'dns',
      subject: { kind: 'domain', value: 'second-private.test' },
      source_ref: 'https://second-private.test',
      observed_at: '2026-09-09T13:00:00Z',
      retrieved_at: '2026-09-09T13:01:00Z',
      payload: { answer: '198.51.100.2' },
    },
  ];
  const posts: { path: string; body: any }[] = [];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const post = route.request().method() === 'POST';
    if (post) posts.push({ path, body: route.request().postDataJSON() });
    if (path === '/api/investigations/case-2')
      return route.fulfill({ json: { ...caseData, id: 'case-2', title: 'İkinci inceleme' } });
    if (path.endsWith('/evidence'))
      return route.fulfill({ json: { items: records, total_unique: 2, next_cursor: null } });
    if (path.includes('/evidence/')) return route.fulfill({ json: records.find((r) => path.endsWith(r.id)) });
    if (path.endsWith('/captures'))
      return route.fulfill({
        json: {
          items: [],
          references: [],
          capabilities: { mode: 'recorded_demo', browser_available: false, ocr_available: false },
        },
      });
    if (path.endsWith('/candidates'))
      return route.fulfill({ json: { items: [], total_unique: 0, next_cursor: null } });
    if (path.endsWith('/story/preview'))
      return route.fulfill({
        json: {
          preview_id: 'frozen-preview',
          title: 'Maskeli inceleme',
          redacted: route.request().postDataJSON().redact,
          steps: [
            { title: 'Kanıt akışı', subtitle: 'İnceleme', body: 'Kimlikleri gizlenmiş sunum.', fields: [] },
            { title: 'İkinci kart', subtitle: 'Dayanak', body: 'İkinci maskeli gözlem.', fields: [] },
          ],
        },
      });
    if (path.endsWith('/story/export'))
      return route.fulfill({ contentType: 'text/html', body: '<html><body>Maskeli sunum</body></html>' });
    return route.fallback();
  });
  await page.goto('/#/investigations/case-1');
  await expect(page.getByRole('heading', { name: caseData.title })).toBeVisible();
  return posts;
}
async function openStory(page: Page) {
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Paylaşım' }).click();
  await expect(page.getByRole('checkbox', { name: 'Kanıtı seç: page · first-private.test' })).toBeVisible();
}
async function pin(page: Page, provider: string) {
  await page.getByRole('button', { name: `${provider} kaynak kaydını aç` }).click();
  await page.getByRole('button', { name: 'Kanıtı panoya sabitle', exact: true }).click();
  await page.getByRole('button', { name: 'Kanıtı kapat', exact: true }).click();
}

test('shared inspector keeps the current tool and selection, then restores source focus', async ({
  page,
}) => {
  await unifiedFixtures(page);
  await openStory(page);
  const selected = page.getByRole('checkbox', { name: 'Kanıtı seç: page · first-private.test' });
  await selected.check();
  const source = page.getByRole('button', { name: 'page kaynak kaydını aç' });
  await source.click();
  await expect(page.getByRole('tab', { name: 'Paylaşım' })).toHaveAttribute('aria-selected', 'true');
  await expect(selected).toBeChecked();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toContainText('İlk sayfa gözlemi');
  await page.getByRole('button', { name: 'Kanıtı kapat', exact: true }).click();
  await expect(source).toBeFocused();
  await page.getByRole('tab', { name: 'Adaylar' }).click();
  await page.getByRole('tab', { name: 'Paylaşım' }).click();
  await expect(selected).toBeChecked();
  await page.getByRole('button', { name: 'Kayıt ve geçmiş' }).click();
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await expect(selected).toBeChecked();
});

test('evidence board reorder transfers exact selection order to frozen preview and export', async ({
  page,
}) => {
  const posts = await unifiedFixtures(page);
  await openStory(page);
  await pin(page, 'page');
  await pin(page, 'dns');
  await page.getByRole('button', { name: 'Kanıt panosu', exact: false }).click();
  const board = page.getByRole('region', { name: 'Kanıt panosu', exact: true });
  await board.getByRole('button', { name: 'Kanıt 2 yukarı' }).click();
  await expect(board.locator('[data-evidence-id]').first()).toHaveAttribute('data-evidence-id', 'ev-2');
  await board.locator('[data-evidence-id="ev-2"]').dragTo(board.locator('[data-evidence-id="ev-1"]'));
  await expect(board.locator('[data-evidence-id]').first()).toHaveAttribute('data-evidence-id', 'ev-1');
  await board.getByRole('button', { name: 'Kanıt 2 yukarı' }).click();
  await page.getByRole('button', { name: 'Panodan aktar' }).click();
  const order = page.getByRole('region', { name: 'Sunum sırası' });
  await expect(order.locator('[data-evidence-id]').first()).toHaveAttribute('data-evidence-id', 'ev-2');
  await page.getByRole('button', { name: 'Önizlemeyi oluştur' }).click();
  await expect(page.getByRole('region', { name: 'Sunum önizlemesi' })).toBeVisible();
  await page.screenshot({ path: '../.local/unified-gui/workspace-desktop-dark.png', fullPage: true });
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'light';
  });
  await page.screenshot({ path: '../.local/unified-gui/workspace-desktop-light.png', fullPage: true });
  expect(posts.find((p) => p.path.endsWith('/preview'))?.body).toEqual({
    evidence_ids: ['ev-2', 'ev-1'],
    redact: true,
  });
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'HTML sunumunu indir' }).click();
  await download;
  expect(posts.find((p) => p.path.endsWith('/export'))?.body).toEqual({
    evidence_ids: ['ev-2', 'ev-1'],
    redact: true,
    preview_id: 'frozen-preview',
  });
  await order.getByRole('button', { name: 'Kanıt 2 yukarı' }).click();
  await expect(page.getByRole('button', { name: 'HTML sunumunu indir' })).toBeDisabled();
});

test('case tabs, story choice and board persist on reload and stay isolated by case', async ({ page }) => {
  await unifiedFixtures(page);
  await openStory(page);
  await pin(page, 'page');
  await page.getByRole('checkbox', { name: 'Kanıtı seç: page · first-private.test' }).check();
  await page.reload();
  await expect(page.getByRole('tab', { name: 'Paylaşım' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('checkbox', { name: 'Kanıtı seç: page · first-private.test' })).toBeChecked();
  await page.getByRole('button', { name: 'Kanıt panosu', exact: false }).click();
  await expect(
    page.getByRole('region', { name: 'Kanıt panosu', exact: true }).locator('[data-evidence-id]'),
  ).toHaveCount(1);
  await page.goto('/#/investigations/case-2');
  await expect(page.getByRole('heading', { name: 'İkinci inceleme' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Araştırma', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByRole('button', { name: 'Kanıt panosu', exact: false }).click();
  await expect(page.getByRole('region', { name: 'Kanıt panosu', exact: true })).toContainText(
    'Henüz sabitlenmiş kanıt yok',
  );
});

test('narrow evidence overlay restores focus and masked presentation hides the case', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await unifiedFixtures(page);
  await openStory(page);
  const source = page.getByRole('button', { name: 'page kaynak kaydını aç' });
  await source.click();
  await expect(page.getByRole('dialog', { name: 'Kanıt inceleyicisi' })).toBeVisible();
  await page.screenshot({ path: '../.local/unified-gui/workspace-narrow-inspector.png' });
  await page.keyboard.press('Escape');
  await expect(source).toBeFocused();
  await page.getByRole('button', { name: 'Önizlemeyi oluştur' }).click();
  await page.getByRole('button', { name: 'Maskeli sunumu aç' }).click();
  const focus = page.getByRole('dialog', { name: 'Maskeli sunum' });
  await expect(focus).toBeVisible();
  await expect(focus).not.toContainText('private.test');
  await page.screenshot({ path: '../.local/unified-gui/workspace-narrow-focus-dark.png' });
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'light';
  });
  await page.screenshot({ path: '../.local/unified-gui/workspace-narrow-focus-light.png' });
  await expect(page.getByRole('heading', { name: 'Örnek Banka incelemesi' })).not.toBeVisible();
  await focus.getByRole('button', { name: 'Sonraki kart' }).click();
  await expect(focus).toContainText('İkinci maskeli gözlem.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Örnek Banka incelemesi' })).toBeVisible();
});

test('board enforces twelve pins and corrupt or unavailable workspace storage stays usable', async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem('belgu:case-workspace:v1:case-1:tool', '"unknown-tool"');
    localStorage.setItem('belgu:case-workspace:v1:case-1:story-selection', '{broken');
    localStorage.setItem(
      'belgu:case-workspace:v1:case-1:evidence-board',
      JSON.stringify(Array.from({ length: 12 }, (_, i) => `old-${i}`)),
    );
  });
  await unifiedFixtures(page);
  await expect(page.getByRole('button', { name: 'Araştırma', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await openStory(page);
  await page.getByRole('button', { name: 'page kaynak kaydını aç' }).click();
  await expect(page.getByRole('button', { name: 'Kanıtı panoya sabitle', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Kanıtı kapat', exact: true }).click();
  await page.addInitScript(() => {
    Storage.prototype.getItem = function () {
      throw new DOMException('Storage disabled');
    };
    Storage.prototype.setItem = function () {
      throw new DOMException('Storage disabled');
    };
  });
  await page.goto('/#/investigations/case-2');
  await page.reload();
  await openStory(page);
  await pin(page, 'page');
  await page.getByRole('button', { name: 'Kanıt panosu', exact: false }).click();
  await expect(
    page.getByRole('region', { name: 'Kanıt panosu', exact: true }).locator('[data-evidence-id]'),
  ).toHaveCount(1);
});

test('Escape closes the top dialog while keeping its underlying evidence open', async ({ page }) => {
  await installApiFixtures(page, { demo: false });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'giris-01.test ayrıntıları', exact: true }).click();
  await page.getByRole('button', { name: 'Bağlantının kanıtını aç', exact: true }).first().click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
  await page.getByRole('button', { name: 'Karar kaydet', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toHaveCount(0);
});
