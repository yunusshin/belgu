import { test, expect } from '@playwright/test';
import { installApiFixtures } from './fixtures';
test('group selection filters entities and opens evidence', async ({ page }) => {
  await installApiFixtures(page);
  await page.goto('/');
  await page.getByRole('link', { name: 'Örnek Banka incelemesi', exact: true }).click();
  await page.getByRole('button', { name: 'JS özeti grubu A, 30 varlık' }).click();
  await expect(page.getByTestId('entity-total')).toHaveText('30 alan adı');
  await page.getByRole('button', { name: 'giris-01.test ayrıntıları' }).click();
  await page.getByRole('button', { name: 'Bağlantının kanıtını aç' }).first().click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
  await expect(page.getByText('Kurmaca demo verisi', { exact: true })).toBeVisible();
});
test('all domains remain reachable with bounded pagination', async ({ page }) => {
  await installApiFixtures(page);
  await page.goto('/#/investigations/case-1');
  await expect(page.getByTestId('entity-total')).toHaveText('120 alan adı');
  await expect(page.getByRole('button', { name: 'giris-01.test ayrıntıları' })).toBeVisible();
  await page.getByRole('button', { name: 'Sonraki sayfa', exact: true }).click();
  await expect(page.getByRole('button', { name: 'giris-26.test ayrıntıları' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'giris-01.test ayrıntıları' })).toHaveCount(0);
});
test('model unavailability preserves investigation access', async ({ page }) => {
  await installApiFixtures(page);
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Model analizi', exact: true }).click();
  await expect(page.getByText('Model kullanılamıyor', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Analizi başlat', exact: true })).toBeDisabled();
});
test('discovery cancellation preserves existing evidence and shows terminal state', async ({ page }) => {
  const { caseData } = await installApiFixtures(page, { demo: false });
  await page.route('**/api/investigations/case-1/jobs', async (route) => {
    const job = {
      id: 'job-1',
      kind: 'collect',
      status: 'running',
      progress: { requests: 3, entities: 4, message: 'Kaynaklar taranıyor' },
      limits: { max_requests: 100 },
      truncated: false,
      error: null,
      cancel_requested: false,
    };
    caseData.jobs.push(job);
    await route.fulfill({ json: job });
  });
  await page.route('**/api/jobs/job-1/cancel', async (route) => {
    caseData.jobs[0].status = 'cancelled';
    caseData.jobs[0].cancel_requested = true;
    await route.fulfill({ json: caseData.jobs[0] });
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Keşfi başlat', exact: true }).click();
  await expect(page.getByText('Kaynaklar taranıyor')).toBeVisible();
  await page.getByRole('button', { name: 'İşi iptal et' }).click();
  await expect(page.getByText('İptal edildi', { exact: true })).toBeVisible();
  await expect(page.getByTestId('entity-total')).toHaveText('120 alan adı');
});
test('stale recorded analysis is labelled and its citation opens source evidence', async ({ page }) => {
  await installApiFixtures(page);
  await page.route('**/api/investigations/case-1/analyses', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'analysis-1',
            status: 'completed',
            output: {
              summary: 'Kayıtlı örnek değerlendirme.',
              claims: [{ text: 'İki sayfada ortak JavaScript içeriği.', evidence_ids: ['ev-1'] }],
            },
            model_id: 'recorded-demo',
            prompt_version: 'v1',
            snapshot_id: 'snapshot-1',
            stale: true,
            created_at: '2026-09-08T10:20:00Z',
            recorded_demo: true,
            metrics: {},
          },
        ],
        total_unique: 1,
        next_cursor: null,
      },
    }),
  );
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Model analizi', exact: true }).click();
  await expect(page.getByText('Kayıtlı demo yanıtı', { exact: true })).toBeVisible();
  await expect(page.getByText('Bu analizden sonra kanıtlar değişti.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Kanıt 1', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toContainText('demo_http');
});
test('case connection failure is explicit and can be retried', async ({ page }) => {
  await installApiFixtures(page);
  let failed = true;
  await page.route('**/api/investigations/case-1', async (route) => {
    if (failed)
      return route.fulfill({
        status: 503,
        json: { error: { message: 'Yerel inceleme servisi geçici olarak kullanılamıyor.' } },
      });
    return route.fallback();
  });
  await page.goto('/#/investigations/case-1');
  await expect(page.getByRole('alert')).toContainText('geçici olarak kullanılamıyor');
  failed = false;
  await page.getByRole('button', { name: 'Yeniden dene' }).click();
  await expect(page.getByTestId('entity-total')).toHaveText('120 alan adı');
});

test('newest running job stays first and cancellable beyond five historical jobs', async ({ page }) => {
  const { caseData } = await installApiFixtures(page, { demo: false });
  caseData.jobs = Array.from({ length: 7 }, (_, index) => ({
    id: `history-job-${index}`,
    kind: 'collect',
    status: index === 0 ? 'running' : 'completed',
    progress: { message: index === 0 ? 'Güncel keşif çalışıyor' : `Geçmiş çalışma ${index}` },
    limits: {},
    truncated: false,
    error: null,
    cancel_requested: false,
    created_at: `2026-09-08T10:0${6 - index}:00Z`,
    updated_at: '2026-09-08T10:06:00Z',
  }));
  await page.route('**/api/jobs/history-job-0/cancel', async (route) => {
    caseData.jobs[0].status = 'cancelled';
    caseData.jobs[0].cancel_requested = true;
    await route.fulfill({ json: caseData.jobs[0] });
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: '1 etkin iş' }).click();
  await expect(page.locator('.case-jobs .job-card')).toHaveCount(5);
  await expect(page.locator('.case-jobs .job-card').first()).toContainText('Güncel keşif çalışıyor');
  await expect(page.getByText('Geçmiş çalışma 6', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'İşi iptal et' }).click();
  await expect(page.locator('.case-jobs .job-card').first()).toContainText('İptal edildi');
});

test('hash and certificate graph nodes cannot expand while domain nodes can', async ({ page }) => {
  await installApiFixtures(page, { demo: false });
  const domain = { id: 'entity-1', kind: 'domain', canonical_value: 'giris-01.test', evidence_count: 1 };
  const hashes = ['cert', 'js_hash', 'favicon_hash'].map((kind) => ({
    id: kind,
    kind,
    canonical_value: `${kind}-sha256`,
    evidence_count: 1,
  }));
  await page.route('**/api/investigations/case-1/graph?**', (route) =>
    route.fulfill({
      json: {
        nodes: [domain, ...hashes],
        relations: hashes.map((node) => ({
          id: node.id,
          src_id: domain.id,
          dst_id: node.id,
          kind: node.kind,
          evidence_ids: ['ev-1'],
        })),
        has_more: false,
        next_cursor: null,
      },
    }),
  );
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'giris-01.test ayrıntıları' }).click();
  await expect(page.getByRole('button', { name: 'Bu varlığı genişlet' })).toBeEnabled();
  for (const node of hashes) {
    await page.getByRole('button', { name: `${node.canonical_value} düğümü` }).click();
    await expect(page.getByRole('button', { name: 'Bu varlığı genişlet' })).toBeDisabled();
  }
  await page.getByRole('button', { name: 'giris-01.test düğümü' }).click();
  await expect(page.getByRole('button', { name: 'Bu varlığı genişlet' })).toBeEnabled();
});

test('fresh analysis discloses included and omitted evidence without implying full coverage', async ({
  page,
}) => {
  await installApiFixtures(page, { demo: false });
  await page.route('**/api/investigations/case-1/analyses', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'partial-analysis',
            status: 'completed',
            output: {
              summary: 'Sınırlı bağlamla oluşturulan değerlendirme.',
              evidence_ids: Array.from({ length: 23 }, (_, index) => `evidence-${index}`),
              omitted_count: 81,
            },
            model_id: 'local-model',
            prompt_version: 'v1',
            snapshot_id: 'current-snapshot',
            stale: false,
            created_at: '2026-09-08T10:20:00Z',
            recorded_demo: false,
            metrics: {},
          },
        ],
        total_unique: 1,
        next_cursor: null,
      },
    }),
  );
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Model analizi', exact: true }).click();
  await expect(
    page.getByText('Model 23 kanıtı değerlendirdi; bağlam sınırı nedeniyle 81 kayıt bu analize alınmadı.', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText('Bu analizden sonra kanıtlar değişti.', { exact: false })).toHaveCount(0);
});

for (const { scopeExcluded, budgetOmitted } of [
  { scopeExcluded: 81, budgetOmitted: 0 },
  { scopeExcluded: 81, budgetOmitted: 5 },
  { scopeExcluded: 0, budgetOmitted: 0 },
]) {
  test(`target analysis distinguishes ${scopeExcluded} scope exclusions from ${budgetOmitted} context omissions`, async ({
    page,
  }) => {
    await installApiFixtures(page, { demo: false });
    await page.route('**/api/investigations/case-1/analyses', (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: 'target-analysis',
              status: 'completed',
              output: {
                summary: 'Hedefe ait kanıtların değerlendirmesi.',
                analysis_scope: 'submitted_targets',
                scope_excluded_count: scopeExcluded,
                budget_omitted_count: budgetOmitted,
                omitted_count: scopeExcluded + budgetOmitted,
                evidence_ids: Array.from({ length: 23 }, (_, index) => `target-evidence-${index}`),
              },
              model_id: 'local-model',
              prompt_version: 'v2',
              snapshot_id: 'target-snapshot',
              stale: false,
              created_at: '2026-09-08T10:20:00Z',
              recorded_demo: false,
              metrics: {},
            },
          ],
          total_unique: 1,
          next_cursor: null,
        },
      }),
    );
    await page.goto('/#/investigations/case-1');
    await page.getByRole('button', { name: 'Model analizi', exact: true }).click();
    await expect(
      page.getByText(
        `Hedef analizi: 23 kanıt değerlendirildi. İlişkili varlıklara ait ${scopeExcluded} kayıt bu değerlendirmenin dışında.`,
        { exact: true },
      ),
    ).toBeVisible();
    if (budgetOmitted) {
      await expect(
        page.getByText(`Bağlam sınırı nedeniyle ${budgetOmitted} kayıt bu analize alınmadı.`, {
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByText(`bağlam sınırı nedeniyle ${scopeExcluded + budgetOmitted} kayıt`, { exact: false }),
      ).toHaveCount(0);
    } else {
      await expect(page.locator('.analysis-content').getByText(/bağlam sınırı/i)).toHaveCount(0);
    }
  });
}

for (const width of [1512, 390]) {
  test(`many provider outcomes retain totals in bounded readable details at ${width}px`, async ({ page }) => {
    const { caseData } = await installApiFixtures(page, { demo: false });
    const providers = Array.from({ length: 63 }, (_, index) => ({
      provider: index < 21 ? 'dns' : index < 42 ? 'page' : `source-${index}`,
      status: index < 21 ? 'ok' : index < 42 ? 'error' : 'ok',
      error_code: index >= 21 && index < 42 ? 'ConnectError' : null,
      observations: index < 21 ? 1 : index < 42 ? 0 : 2,
      truncated: false,
    }));
    caseData.jobs = [
      {
        id: 'many-provider-job',
        kind: 'collect',
        status: 'partial',
        progress: {
          requests: 100,
          entities: 283,
          remaining_requests: 0,
          elapsed_seconds: 38,
          new_entities: 282,
          observations: 63,
          provider_count: 63,
          providers,
        },
        limits: { max_requests: 100 },
        truncated: true,
        error: null,
        cancel_requested: false,
      },
    ];
    await page.setViewportSize({ width, height: 1100 });
    await page.goto('/#/investigations/case-1');
    await page.getByRole('button', { name: '1 çalışma' }).click();
    await page.getByRole('button', { name: 'İş ayrıntıları', exact: true }).click();
    const results = page.getByRole('region', { name: 'Kaynak sonuçları' });
    await expect(results).toContainText('63 deneme');
    await expect(results).toContainText('63 gözlem');
    const dns = results.getByRole('listitem').filter({ has: page.getByText('DNS', { exact: true }) });
    await expect(dns).toContainText('21 deneme');
    await expect(dns).toContainText('21 gözlem');
    const failed = results.getByRole('listitem').filter({ hasText: 'Bağlantı kurulamadı' });
    await expect(failed).toContainText('21 deneme');
    await expect(failed).toContainText('0 gözlem');
    await expect(results.getByRole('listitem')).toHaveCount(23);
    await expect(page.locator('.job-details')).not.toContainText('{"provider"');
    for (const label of ['Kalan istek', 'Geçen süre (sn)', 'Yeni varlık', 'Gözlem', 'Kaynak denemesi'])
      await expect(
        page
          .locator('.job-details dt')
          .filter({ hasText: new RegExp(`^${label.replace(/[()]/g, '\\$&')}$`) }),
      ).toBeVisible();
    const bounds = await results
      .getByRole('list')
      .evaluate((el) => ({ height: el.clientHeight, scrollHeight: el.scrollHeight }));
    expect(bounds.height).toBeLessThanOrEqual(320);
    expect(bounds.scrollHeight).toBeGreaterThan(bounds.height);
    await results.getByRole('listitem').last().scrollIntoViewIfNeeded();
    await expect(results.getByRole('listitem').last()).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await expect(page.getByText('Çalışma sınırları', { exact: true })).toBeVisible();
  });
}

test('analysis job labels legacy entities counter as investigation evidence', async ({ page }) => {
  const { caseData } = await installApiFixtures(page, { demo: false });
  caseData.entity_count = 283;
  caseData.evidence_count = 324;
  caseData.jobs = [
    {
      id: 'analysis-counter',
      kind: 'analysis',
      status: 'completed',
      progress: { entities: 324 },
      limits: {},
      truncated: false,
      error: null,
      cancel_requested: false,
    },
  ];
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: '1 çalışma' }).click();
  await page.getByRole('button', { name: 'İş ayrıntıları', exact: true }).click();
  const count = page
    .locator('.job-details dl>div')
    .filter({ has: page.getByText('İnceleme kanıtı', { exact: true }) });
  await expect(count.locator('dd')).toHaveText('324');
  await expect(page.locator('.job-details dt').filter({ hasText: /^Varlık$/ })).toHaveCount(0);
});

test('provider quota, transport and upstream HTTP outcomes have readable labels', async ({ page }) => {
  const { caseData } = await installApiFixtures(page, { demo: false });
  const codes = [
    'https_transport_failed',
    'page_connecterror',
    'page_connecttimeout',
    'page_readtimeout',
    'upstream_http_400',
    'upstream_http_403',
    'upstream_rate_limited',
    'upstream_access_denied',
    'unknown_provider_code',
  ];
  caseData.jobs = [
    {
      id: 'provider-labels',
      kind: 'collect',
      status: 'partial',
      progress: {
        providers: codes.map((error_code, index) => ({
          provider: index === 0 ? 'sgb' : index === 1 ? 'threatfox' : 'page',
          status: index === 6 ? 'rate_limited' : 'error',
          error_code,
          observations: 0,
          truncated: false,
        })),
      },
      limits: {},
      truncated: false,
      error: null,
      cancel_requested: false,
    },
  ];
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: '1 çalışma' }).click();
  await page.getByRole('button', { name: 'İş ayrıntıları', exact: true }).click();
  const results = page.getByRole('region', { name: 'Kaynak sonuçları' });
  for (const label of [
    'Kaynak kotası doldu',
    'HTTPS bağlantısı kurulamadı',
    'Sayfaya bağlantı kurulamadı',
    'Sayfa bağlantı süresi aşıldı',
    'Sayfa yanıt süresi aşıldı',
    'HTTP 400 yanıtı alındı',
    'HTTP 403 yanıtı alındı',
    'Kaynak erişimi reddetti',
    'SGB',
    'ThreatFox',
    'unknown_provider_code',
  ])
    await expect(results.getByText(label, { exact: true }).first()).toBeVisible();
  await expect(results).not.toContainText('upstream_http_400');
  await expect(results).not.toContainText('page_connecterror');
});
