import { expect, test, type Page } from '@playwright/test';
import { installApiFixtures } from './fixtures';

const at = '2026-09-08T10:20:00Z';

async function openReplay(page: Page, runningJob = false, graphSize = 1) {
  const { caseData } = await installApiFixtures(page);
  if (runningJob)
    caseData.jobs.push({
      id: 'polling-job',
      investigation_id: 'case-1',
      kind: 'collect',
      status: 'running',
      progress: {},
      limits: {},
      error: null,
      truncated: false,
      cancel_requested: false,
      created_at: at,
      updated_at: at,
    });
  const requests: any[] = [];
  const replayNodes = Array.from({ length: graphSize }, (_, index) => ({
    id: `node-${index + 1}`,
    kind: 'domain',
    label: `Hedef ${String(index + 1).padStart(2, '0')} uzun görünür etiket`,
  }));
  await page.route('**/api/investigations/case-1/replay/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON();
    requests.push({ path, body });
    if (path.endsWith('/export')) {
      return route.fulfill({
        contentType: 'text/html',
        headers: { 'content-disposition': 'attachment; filename="belgu-kayitli-inceleme.html"' },
        body: '<!doctype html><html><body>Kayıtlı inceleme</body></html>',
      });
    }
    const redacted = body.redact;
    await route.fulfill({
      json: {
        preview_id: redacted ? 'maskeli-preview' : 'acik-preview',
        title: redacted ? 'Belgü · Kayıtlı inceleme' : 'Örnek Banka incelemesi',
        redacted,
        recorded: true,
        timing_basis: 'known_at',
        created_at: at,
        events: [
          {
            id: 'event-001',
            kind: 'submission',
            title: 'Başlangıç kaydı',
            known_at: at,
            observed_at: null,
            scope: redacted ? 'active_case' : 'case-1',
            status: 'recorded',
            evidence_refs: [],
            detail: redacted ? 'İncelemeye bir başlangıç kaydı eklendi.' : 'giris-01.test',
            graph_additions: {
              nodes: replayNodes.map((node, index) =>
                redacted
                  ? node
                  : {
                      ...node,
                      id: index ? `entity-${index + 1}` : 'entity-1',
                      label: index ? `giris-${index + 1}.test` : 'giris-01.test',
                    },
              ),
              edges: [],
            },
          },
          {
            id: 'event-002',
            kind: 'observation',
            title: 'Kaynak gözlemi',
            known_at: '2026-09-08T10:21:00Z',
            observed_at: '2025-01-03T07:00:00Z',
            scope: redacted ? 'active_case' : 'case-1',
            status: 'recorded',
            evidence_refs: [redacted ? 'evidence-001' : 'ev-1'],
            detail: redacted ? 'Bir kaynak gözlemi kayda alındı.' : 'browser_capture · giris-01.test',
            graph_additions: { nodes: [], edges: [] },
          },
          {
            id: 'event-003',
            kind: 'job',
            title: 'Çalışma sonucu',
            known_at: '2026-09-08T10:22:00Z',
            observed_at: null,
            scope: redacted ? 'active_case' : 'case-1',
            status: 'failed',
            evidence_refs: [],
            detail: redacted
              ? 'Çalışmanın kaydedilmiş durumu zaman çizelgesine eklendi.'
              : 'capture · zaman aşımı',
            graph_additions: { nodes: [], edges: [] },
          },
        ],
        graph: { nodes: [], edges: [] },
        counts: {
          available: { submission: 1, observation: 1, job: 1 },
          included: { submission: 1, observation: 1, job: 1 },
        },
        coverage: {
          available_events: 3,
          included_events: 3,
          omitted_events: 0,
          event_limit: 160,
          available_graph_nodes: graphSize,
          included_graph_nodes: graphSize,
          omitted_graph_nodes: 0,
          graph_node_limit: 60,
          relation_records: 0,
          supported_relation_events: 0,
          included_relation_events: 0,
          rendered_graph_edges: 0,
          omitted_graph_edges: 0,
          included_relations: 0,
          unsupported_relations: 0,
          omitted_evidence_lifecycle_events: 0,
          events_truncated: false,
          graph_truncated: false,
        },
        limitations: ['Bu oynatma kayıtlardan yeniden oluşturulur.'],
      },
    });
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Tekrar oynat', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Kayıtlı inceleme oynatması' })).toBeVisible();
  return requests;
}

test('recorded replay supports play, seek, steps, masking and exact preview export', async ({ page }) => {
  const requests = await openReplay(page);
  const replay = page.getByRole('region', { name: 'Kayıtlı inceleme oynatması' });
  await expect(replay).toContainText('Kayıtlardan yeniden oluşturuldu');
  await expect(replay).toContainText('Başlangıç kaydı');
  await page.getByRole('button', { name: 'Sonraki kayıt', exact: true }).click();
  await expect(replay).toContainText('Kaynak gözlemi');
  await expect(replay).toContainText('3 Oca 2025', { ignoreCase: true });
  await page.getByRole('button', { name: 'Kaydı oynat', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Kaydı duraklat', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Kaydı duraklat', exact: true }).click();
  await page.getByLabel('Kayıtta ara').fill('2');
  await expect(replay).toContainText('Başarısız');
  await page.getByLabel('Oynatma hızı').selectOption('2');

  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Çevrimdışı HTML indir', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('belgu-kayitli-inceleme.html');
  expect(requests.find((request) => request.path.endsWith('/export')).body).toEqual({
    preview_id: 'maskeli-preview',
    redact: true,
  });

  await page.getByRole('button', { name: 'Maskeli odak görünümünü aç', exact: true }).click();
  const focus = page.getByRole('dialog', { name: 'Maskeli kayıtlı inceleme' });
  await expect(focus).toBeVisible();
  await expect(focus).not.toContainText('Örnek Banka incelemesi');
  await page.getByRole('button', { name: 'Odak görünümünü kapat', exact: true }).click();

  await page.getByLabel('Kimlikleri maskele', { exact: true }).uncheck();
  await expect(replay).toContainText('giris-01.test');
  await page.getByLabel('Kayıtta ara').fill('1');
  await page.getByRole('button', { name: 'Kanıt ev-1 kaydını aç', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
});

test('background job polling does not replace the saved preview or reset the chosen frame', async ({
  page,
}) => {
  const requests = await openReplay(page, true);
  const replay = page.getByRole('region', { name: 'Kayıtlı inceleme oynatması' });
  await page.getByRole('button', { name: 'Sonraki kayıt', exact: true }).click();
  await expect(replay).toContainText('Kaynak gözlemi');
  const previewCount = requests.filter((request) => request.path.endsWith('/preview')).length;
  await page.waitForTimeout(2800);
  await expect(replay).toContainText('Kaynak gözlemi');
  expect(requests.filter((request) => request.path.endsWith('/preview'))).toHaveLength(previewCount);
});

test('near-limit graph uses compact nodes while preserving every full label', async ({ page }) => {
  await openReplay(page, false, 60);
  const graph = page.getByRole('img', { name: 'İnceleme grafiğinin kayıtlı durumu' });
  await expect(graph.locator('circle')).toHaveCount(60);
  await expect(graph.locator('title')).toHaveCount(60);
  await expect(graph.locator('title').first()).toHaveText('Hedef 01 uzun görünür etiket');
  await page.screenshot({ path: 'test-results/replay-near-limit.png', fullPage: true });
});

test('recorded replay remains usable at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openReplay(page);
  await expect(page.getByRole('button', { name: 'Önceki kayıt', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBeFalsy();
});
