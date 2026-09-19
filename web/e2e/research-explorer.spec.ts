import { test, expect, type Page } from '@playwright/test';
import { installApiFixtures } from './fixtures';
async function explorer(page: Page, running = false) {
  const { caseData } = await installApiFixtures(page),
    requests: URL[] = [];
  if (running)
    caseData.jobs.push({
      id: 'running-discovery',
      kind: 'collect',
      status: 'running',
      progress: { message: 'Fixture polling' },
      limits: {},
      truncated: false,
      error: null,
      cancel_requested: false,
      created_at: '2026-09-10T10:00:00Z',
      updated_at: '2026-09-10T10:00:00Z',
    });
  const entities = Array.from({ length: 120 }, (_, i) => ({
    id: `entity-${i + 1}`,
    kind: 'domain',
    canonical_value: `domain-${String(i + 1).padStart(3, '0')}.test`,
    evidence_count: 2,
    last_seen: '2026-09-10T10:00:00Z',
    has_capture: i % 2 === 0,
    shared_signals: i % 3 === 1 ? ['javascript'] : ['certificate'],
    priority_score: i,
  }));
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    let body: unknown;
    if (url.pathname.endsWith('/entities')) {
      requests.push(url);
      let items = entities.filter((item) => item.canonical_value.includes(url.searchParams.get('q') || ''));
      if (url.searchParams.get('has_capture') === 'true') items = items.filter((item) => item.has_capture);
      if (url.searchParams.get('shared'))
        items = items.filter((item) => item.shared_signals.includes(url.searchParams.get('shared')!));
      if (url.searchParams.get('recent_hours'))
        items = items.filter((item) => Number(item.id.split('-')[1]) > 80);
      if (url.searchParams.get('sort') === 'priority') items = [...items].reverse();
      if (url.searchParams.get('kind') === 'ip') items = [];
      const start = Number(url.searchParams.get('cursor') || 0),
        limit = Number(url.searchParams.get('limit') || 25);
      body = {
        items: items.slice(start, start + limit),
        total_unique: items.length,
        next_cursor: start + limit < items.length ? String(start + limit) : null,
      };
    } else if (url.pathname.endsWith('/graph')) {
      requests.push(url);
      const root = entities.find((item) => item.id === url.searchParams.get('root_id')) || entities[0];
      const start = Number(url.searchParams.get('cursor') || 0),
        limit = Number(url.searchParams.get('limit') || 25);
      const neighbors = entities.filter((item) => item.id !== root.id).slice(start, start + limit);
      body = {
        nodes: [root, ...neighbors],
        relations: neighbors.map((node) => ({
          id: `${root.id}-${node.id}`,
          src_id: root.id,
          dst_id: node.id,
          kind: 'certificate_names',
          evidence_ids: ['ev-1', 'ev-2'],
        })),
        has_more: start + limit < 119,
        next_cursor: start + limit < 119 ? String(start + limit) : null,
      };
    } else if (url.pathname.endsWith('/candidates')) {
      requests.push(url);
      const start = Number(url.searchParams.get('cursor') || 0),
        limit = Number(url.searchParams.get('limit') || 30);
      body = {
        items: entities
          .slice(0, 65)
          .slice(start, start + limit)
          .map((item, index) => ({
            entity_id: item.id,
            domain: item.canonical_value,
            score: 70 - start - index,
            priority: 'medium',
            reasons: [{ label: 'Aynı sertifika', strength: 'moderate', evidence_ids: ['ev-1'] }],
            limitations: ['İnceleme önceliğidir.'],
            evidence_ids: ['ev-1'],
          })),
        total_unique: 65,
        next_cursor: start + limit < 65 ? String(start + limit) : null,
      };
    } else if (url.pathname === '/api/investigations/case-2')
      body = { ...caseData, id: 'case-2', title: 'Başka araştırma' };
    else return route.fallback();
    await route.fulfill({ json: body });
  });
  await page.goto('/#/investigations/case-1');
  await expect(page.getByTestId('entity-total')).toHaveText('120 alan adı');
  return { requests };
}
test('case-wide search reaches entity 101 and sends combined filters and sort before pagination', async ({
  page,
}) => {
  const { requests } = await explorer(page);
  await page.getByRole('button', { name: 'Sonraki sayfa', exact: true }).click();
  await expect(page.getByRole('button', { name: 'domain-026.test ayrıntıları', exact: true })).toBeVisible();
  await page.getByLabel('Araştırmadaki tüm varlıklarda ara').fill('101');
  await expect(page.getByRole('button', { name: 'domain-101.test ayrıntıları', exact: true })).toBeVisible();
  await expect(page.getByTestId('entity-total')).toHaveText('1 alan adı');
  await page.getByLabel('Görsel kanıtı olanlar').check();
  await page.getByLabel('Ortak bulgu').selectOption('javascript');
  await page.getByLabel('Son 24 saatte gözlenenler').check();
  await page.getByLabel('Varlıkları sırala').selectOption('priority');
  await expect
    .poll(() =>
      Object.fromEntries(requests.filter((url) => url.pathname.endsWith('/entities')).at(-1)!.searchParams),
    )
    .toMatchObject({
      q: '101',
      has_capture: 'true',
      shared: 'javascript',
      recent_hours: '24',
      sort: 'priority',
    });
  expect(
    requests
      .filter((url) => url.searchParams.get('q') === '101')
      .every((url) => !url.searchParams.has('cursor')),
  ).toBeTruthy();
  await expect(page.getByRole('button', { name: 'domain-101.test ayrıntıları', exact: true })).toBeVisible();
});
test('saved views, selection and pins persist through navigation and reload without crossing cases', async ({
  page,
}) => {
  await explorer(page);
  await page.getByLabel('Araştırmadaki tüm varlıklarda ara').fill('101');
  await page.getByLabel('Seç: domain-101.test', { exact: true }).check();
  await page.getByLabel('Görünüm adı').fill('Özel inceleme');
  await page.getByRole('button', { name: 'Görünümü kaydet', exact: true }).click();
  await page.getByRole('button', { name: 'Seçilenleri grafiğe sabitle', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'domain-101.test sabitlemesini kaldır', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: /^Kayıt ve geçmiş/ }).click();
  await page.getByRole('button', { name: 'Araştırma', exact: true }).click();
  await expect(page.getByLabel('Seç: domain-101.test', { exact: true })).toBeChecked();
  await page.reload();
  await expect(page.getByLabel('Araştırmadaki tüm varlıklarda ara')).toHaveValue('101');
  await expect(page.getByLabel('Seç: domain-101.test', { exact: true })).toBeChecked();
  await page.getByRole('button', { name: 'Filtreleri temizle', exact: true }).click();
  await page.getByLabel('Kayıtlı görünüm').selectOption({ label: 'Özel inceleme' });
  await expect(page.getByLabel('Araştırmadaki tüm varlıklarda ara')).toHaveValue('101');
  await page.goto('/#/investigations/case-2');
  await expect(page.getByRole('heading', { name: 'Başka araştırma' })).toBeVisible();
  await expect(page.getByLabel('Araştırmadaki tüm varlıklarda ara')).toHaveValue('');
  await expect(page.getByLabel('Kayıtlı görünüm').locator('option')).toHaveCount(1);
  await expect(
    page.getByRole('button', { name: 'domain-101.test sabitlemesini kaldır', exact: true }),
  ).toHaveCount(0);
});
test('graph appends neighbor pages, retains pins and trail, and opens cited evidence', async ({ page }) => {
  const { requests } = await explorer(page);
  await page.getByRole('button', { name: 'domain-001.test ayrıntıları', exact: true }).click();
  await expect(page.getByRole('button', { name: 'domain-026.test düğümü', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Seçili düğümü sabitle', exact: true }).click();
  await page.getByRole('button', { name: 'Sonraki bağlantıları ekle', exact: true }).click();
  await expect(page.getByRole('button', { name: 'domain-051.test düğümü', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'domain-002.test düğümü', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Grafik araştırma izi' })).toContainText(
    'domain-001.test',
  );
  await expect(page.getByRole('navigation', { name: 'Grafik araştırma izi' })).toContainText(
    'domain-002.test',
  );
  await expect(
    page.getByRole('button', { name: 'domain-001.test sabitlemesini kaldır', exact: true }),
  ).toBeVisible();
  await page.locator('.research-edge-list summary').click();
  await page.locator('[data-edge-id="entity-2-entity-1"]').click();
  await expect(page.locator('.inspector')).toContainText('Kaynağa yakından bakın');
  await expect(page.locator('.inspector')).toContainText('demo_http');
  expect(
    requests.some(
      (url) =>
        url.pathname.endsWith('/graph') &&
        url.searchParams.get('root_id') === 'entity-1' &&
        url.searchParams.get('cursor') === '25',
    ),
  ).toBeTruthy();
  await page
    .getByRole('navigation', { name: 'Grafik araştırma izi' })
    .getByRole('button', { name: 'domain-001.test', exact: true })
    .click();
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: 'Sonraki bağlantıları ekle', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Sonraki bağlantıları ekle', exact: true })).not.toHaveText(
      'Yükleniyor…',
    );
  }
  await expect(page.getByRole('button', { name: 'domain-120.test düğümü', exact: true })).toBeVisible();
  expect(await page.locator('.research-graph-svg [data-node-id]').count()).toBeLessThanOrEqual(60);
});
test('candidate 31 and final page remain reachable with correct ranges', async ({ page }) => {
  const { requests } = await explorer(page);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Adaylar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'domain-001.test', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Sonraki aday sayfası', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'domain-031.test', exact: true })).toBeVisible();
  await expect(page.getByText('31–60 / 65 aday', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Sonraki aday sayfası', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'domain-065.test', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sonraki aday sayfası', exact: true })).toBeDisabled();
  expect(
    requests.some((url) => url.pathname.endsWith('/candidates') && url.searchParams.get('cursor') === '30'),
  ).toBeTruthy();
});
test('narrow research layout tolerates invalid saved state', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('belgu:research:v1:case-1', '{not json'));
  await page.setViewportSize({ width: 390, height: 900 });
  await explorer(page);
  await page.getByLabel('Araştırmadaki tüm varlıklarda ara').fill('101');
  await expect(page.getByRole('button', { name: 'domain-101.test ayrıntıları', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBeFalsy();
});

test('returning to a cached node cancels a slow expansion without leaving controls busy', async ({
  page,
}) => {
  await explorer(page);
  await page.route('**/api/investigations/case-1/graph?**', async (route) => {
    if (new URL(route.request().url()).searchParams.get('root_id') === 'entity-2')
      await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fallback().catch(() => {});
  });
  await page.getByRole('button', { name: 'domain-001.test ayrıntıları', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sonraki bağlantıları ekle', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'domain-002.test düğümü', exact: true }).click();
  await expect(page.getByText('Bağlantılar yükleniyor…', { exact: true })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'Grafik araştırma izi' })
    .getByRole('button', { name: 'domain-001.test', exact: true })
    .click();
  await expect(page.getByRole('button', { name: 'Sonraki bağlantıları ekle', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Sonraki bağlantıları ekle', exact: true }).click();
  await expect(page.getByRole('button', { name: 'domain-051.test düğümü', exact: true })).toBeVisible();
});

test('cached neighborhoods return to the canvas and evicted branches reload', async ({ page }) => {
  await explorer(page);
  await page.route('**/api/investigations/case-1/graph?**', async (route) => {
    const id = new URL(route.request().url()).searchParams.get('root_id')!;
    const branch = Number(id.split('-')[1]);
    const nodes = Array.from({ length: 25 }, (_, index) => ({
      id: `neighbor-${branch}-${index}`,
      kind: 'domain',
      canonical_value: `branch-${branch}-${index}.test`,
      evidence_count: 1,
      last_seen: null,
    }));
    await route.fulfill({
      json: {
        nodes: [
          { id, kind: 'domain', canonical_value: `domain-${String(branch).padStart(3, '0')}.test` },
          ...nodes,
        ],
        relations: nodes.map((node) => ({
          id: `${id}-${node.id}`,
          src_id: id,
          dst_id: node.id,
          kind: 'certificate_names',
          evidence_ids: ['ev-1'],
        })),
        has_more: false,
        next_cursor: null,
      },
    });
  });
  for (let branch = 1; branch <= 4; branch++) {
    await page
      .getByRole('button', {
        name: `domain-${String(branch).padStart(3, '0')}.test ayrıntıları`,
        exact: true,
      })
      .click();
    await expect(
      page.getByRole('button', { name: `branch-${branch}-24.test düğümü`, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole('navigation', { name: 'Grafik araştırma izi' })
    .getByRole('button', { name: 'domain-001.test', exact: true })
    .click();
  await expect(page.getByRole('button', { name: 'branch-1-24.test düğümü', exact: true })).toBeVisible();
  for (let branch = 5; branch <= 15; branch++) {
    await page
      .getByRole('button', {
        name: `domain-${String(branch).padStart(3, '0')}.test ayrıntıları`,
        exact: true,
      })
      .click();
    await expect(
      page.getByRole('button', { name: `branch-${branch}-24.test düğümü`, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole('navigation', { name: 'Grafik araştırma izi' })
    .getByRole('button', { name: 'domain-001.test', exact: true })
    .click();
  await expect(page.getByRole('button', { name: 'branch-1-24.test düğümü', exact: true })).toBeVisible();
});

test('background discovery polling preserves the selected candidate page', async ({ page }) => {
  await explorer(page, true);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Adaylar', exact: true }).click();
  await page.getByRole('button', { name: 'Sonraki aday sayfası', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'domain-031.test', exact: true })).toBeVisible();
  await page.waitForResponse((response) => new URL(response.url()).pathname === '/api/investigations/case-1');
  await expect(page.getByText('31–60 / 65 aday', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'domain-031.test', exact: true })).toBeVisible();
});
