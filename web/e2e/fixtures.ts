import type { Page } from '@playwright/test';
export async function installApiFixtures(page: Page, options: { demo?: boolean } = {}) {
  const entities = Array.from({ length: 120 }, (_, i) => ({
    id: `entity-${i + 1}`,
    kind: 'domain',
    canonical_value: `giris-${String(i + 1).padStart(2, '0')}.test`,
    evidence_count: 2,
    last_seen: '2026-09-08T10:20:00Z',
  }));
  const caseData = {
    id: 'case-1',
    title: 'Örnek Banka incelemesi',
    brand_id: 'brand-1',
    brand_name: 'Örnek Banka',
    workflow: 'open',
    disposition: 'unreviewed',
    priority: 'high',
    created_at: '2026-09-08T10:00:00Z',
    updated_at: '2026-09-08T10:20:00Z',
    entity_count: 220,
    evidence_count: 340,
    source: 'customer_report',
    demo: options.demo ?? true,
    submissions: [
      {
        id: 's1',
        source: 'customer_report',
        note: 'Şüpheli giriş ekranı',
        target: {
          raw_value: 'https://giris-01.test/login?ref=report',
          kind: 'url',
          canonical_value: 'https://giris-01.test/login?ref=report',
          hostname: 'giris-01.test',
        },
      },
    ],
    notes: [],
    decisions: [],
    attachments: [],
    jobs: [] as any[],
  };
  const collection = (items: unknown[]) => ({ items, next_cursor: null, total_unique: items.length });
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname;
    if (!path.startsWith('/api/')) return route.continue();
    let body: any = {};
    if (path === '/api/health')
      body = {
        status: 'ok',
        mode: options.demo === false ? 'operational' : 'demo',
        worker: { status: 'ready' },
        model: { status: 'unavailable' },
      };
    else if (path === '/api/models')
      body = {
        items: [
          { status: 'unavailable', model_id: 'local-model', message: 'Yerel model servisine ulaşılamıyor.' },
        ],
        status: 'unavailable',
      };
    else if (path === '/api/brands')
      body = collection([{ id: 'brand-1', name: 'Örnek Banka', official_domains: ['ornekbanka.test'] }]);
    else if (path === '/api/investigations') body = collection([caseData]);
    else if (path.endsWith('/groups'))
      body = collection(
        ['A', 'B', 'C', 'D'].map((v, i) => ({
          key: `js-${i}`,
          label: `JS özeti grubu ${v}`,
          criterion: 'js_sha256',
          entity_count: 30,
          evidence_ids: ['ev-1', 'ev-2'],
        })),
      );
    else if (path.endsWith('/entities')) {
      let list = url.searchParams.get('kind') === 'ip' ? [] : entities;
      if (url.searchParams.get('group_key')) list = list.slice(0, 30);
      const offset = Number(url.searchParams.get('cursor') || 0),
        limit = Number(url.searchParams.get('limit') || 25);
      body = {
        items: list.slice(offset, offset + limit),
        total_unique: list.length,
        next_cursor: offset + limit < list.length ? String(offset + limit) : null,
      };
    } else if (path.endsWith('/graph'))
      body = {
        nodes: [entities[0], { id: 'ip-1', kind: 'ip', canonical_value: '203.0.113.1' }],
        relations: [
          { id: 'rel-1', src_id: 'entity-1', dst_id: 'ip-1', kind: 'observed_ip', evidence_ids: ['ev-1'] },
        ],
        has_more: false,
        next_cursor: null,
      };
    else if (path.includes('/evidence/'))
      body = {
        id: 'ev-1',
        subject: { kind: 'domain', value: 'giris-01.test' },
        provider: 'demo_http',
        source_ref: 'https://giris-01.test/app.js',
        observed_at: '2026-09-08T10:20:00Z',
        retrieved_at: '2026-09-08T10:21:00Z',
        payload: { js_sha256: 'a92f4e', note: 'Kayıtlı HTTP gözlemi' },
      };
    else if (path.endsWith('/analyses')) body = collection([]);
    else if (path === '/api/investigations/case-1') body = caseData;
    else
      return route.fulfill({
        status: 404,
        json: { error: { code: 'not_found', message: 'Fixture endpoint unavailable' } },
      });
    await route.fulfill({ json: body });
  });
  return { caseData };
}
