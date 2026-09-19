import { test, expect, type Page } from '@playwright/test';
import { installApiFixtures } from './fixtures';
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf9sAAAAASUVORK5CYII=';
const at = '2026-09-08T10:20:00Z';
async function desk(page: Page, demo = false) {
  const { caseData } = await installApiFixtures(page, { demo });
  const references: object[] = [],
    requests: { path: string; body: any }[] = [];
  const watch = {
    id: 'watch-1',
    entity_id: null,
    target: 'Başlangıç bulguları',
    enabled: true,
    interval_minutes: 60,
    next_run_at: at,
    last_job_id: null,
    last_error: null,
  };
  const alerts = [
    {
      id: 'alert-1',
      kind: 'change',
      message: 'DNS adresi değişti.',
      job_id: 'run-2',
      read: false,
      created_at: at,
    },
  ];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname,
      method = route.request().method();
    let body: any;
    if (method !== 'GET' && !path.endsWith('/attachments'))
      requests.push({ path, body: route.request().postDataJSON() });
    if (path.endsWith('/captures') && method === 'GET')
      body = {
        items: [
          {
            id: 'capture-1',
            evidence_id: 'ev-1',
            url: 'https://giris-01.test/login',
            final_url: 'https://giris-01.test/login',
            observed_at: at,
            artifact_id: 'image-1',
            image_url: '/api/fixture-image',
            text: 'Hesabınıza giriş yapın',
            ocr_text: 'Giriş',
            ocr_status: 'ok',
            forms: [{ action: '/login', method: 'post', inputs: [{ name: 'password', type: 'password' }] }],
            status_code: 200,
          },
        ],
        references,
        capabilities: { status: 'ready', message: 'Tarayıcı hazır.', ocr_available: true },
      };
    else if (path.endsWith('/captures') && method === 'POST') {
      body = {
        id: 'capture-job',
        kind: 'capture',
        status: 'queued',
        progress: {},
        limits: {},
        error: null,
        truncated: false,
        cancel_requested: false,
      };
      caseData.jobs.push(body);
    } else if (path.endsWith('/brands/brand-1/attachments') && method === 'POST') {
      references.push({ id: 'ref-1', image_url: '/api/fixture-image', created_at: at });
      body = { id: 'ref-1' };
    } else if (path.endsWith('/candidates'))
      body = {
        items: [
          {
            entity_id: 'entity-2',
            domain: 'giris-02.test',
            score: 72,
            priority: 'high',
            reasons: [{ label: 'Ortak JavaScript içeriği', strength: 'strong', evidence_ids: ['ev-1'] }],
            limitations: ['Puan bir olasılık değildir.'],
            evidence_ids: ['ev-1'],
          },
        ],
        total_unique: 1,
      };
    else if (path.endsWith('/submissions') && method === 'POST') body = { id: 's2' };
    else if (path.endsWith('/runs'))
      body = {
        items: [
          { id: 'run-2', created_at: at, status: 'completed', evidence_count: 2, approximate: false },
          {
            id: 'run-1',
            created_at: '2026-09-07T10:20:00Z',
            status: 'partial',
            evidence_count: 1,
            approximate: true,
          },
        ],
        total_unique: 2,
      };
    else if (path.endsWith('/changes'))
      body = {
        before: 'run-1',
        after: 'run-2',
        changes: [
          {
            kind: 'changed',
            subject: 'giris-01.test',
            field: 'addresses',
            before: ['203.0.113.1'],
            after: ['203.0.113.2'],
            evidence_ids: ['ev-2'],
            message: 'DNS adresi değişti.',
          },
        ],
        counts: { new: 0, changed: 1, not_observed: 0 },
        limitations: ['Önceki çalışma yaklaşık olarak yeniden oluşturuldu.'],
      };
    else if (path.endsWith('/watches') && method === 'GET') body = { items: [watch], alerts };
    else if (path.endsWith('/watches') && method === 'POST') body = watch;
    else if (path.endsWith('/watches/watch-1') && method === 'PATCH') {
      Object.assign(watch, route.request().postDataJSON());
      body = watch;
    } else if (path.endsWith('/watches/watch-1/run'))
      body = {
        id: 'watch-job',
        kind: 'collect',
        status: 'queued',
        progress: {},
        limits: {},
        error: null,
        truncated: false,
        cancel_requested: false,
      };
    else if (path.endsWith('/alerts/alert-1/read')) {
      alerts[0].read = true;
      body = { ok: true };
    } else if (path.endsWith('/evidence'))
      body = {
        items: ['ev-1', 'ev-2'].map((id, i) => ({
          id,
          investigation_id: 'case-1',
          subject: { kind: 'domain', value: 'giris-01.test' },
          kind: i ? 'dns' : 'page',
          provider: i ? 'dns' : 'browser_capture',
          observed_at: at,
          retrieved_at: at,
          source_ref: '',
          payload: {},
        })),
        total_unique: 2,
        next_cursor: null,
      };
    else if (path.endsWith('/story/preview'))
      body = {
        preview_id: 'preview-fixture',
        title: 'İnceleme sunumu',
        redacted: route.request().postDataJSON().redact,
        created_at: at,
        steps: [
          {
            title: 'Kanıt 1',
            subtitle: 'Sayfa gözlemi',
            body: 'Maskelenmiş gözlem',
            fields: [{ label: 'Kaynak', value: 'Tarayıcı' }],
          },
          { title: 'Kanıt 2', subtitle: 'DNS', body: 'DNS gözlemi', fields: [] },
        ],
      };
    else if (path.endsWith('/story/export'))
      return route.fulfill({
        contentType: 'text/html',
        body: '<!doctype html><html><body>Maskelenmiş gözlem</body></html>',
      });
    else if (path.endsWith('/fixture-image'))
      return route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') });
    else return route.fallback();
    await route.fulfill({ json: body });
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  return { requests, watch, alerts };
}
test('visual desk shows capture forms and OCR, uploads reference and queues capture', async ({ page }) => {
  const { requests } = await desk(page);
  await expect(page.getByAltText('Yakalanan sayfa')).toBeVisible();
  await expect(page.getByText('password', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('OCR metni', { exact: true })).toBeVisible();
  await page
    .getByLabel('Marka referansı yükle')
    .setInputFiles({ name: 'reference.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') });
  await expect(page.getByAltText('Marka referansı')).toBeVisible();
  await page.getByRole('button', { name: 'Görüntü al', exact: true }).click();
  await expect(page.getByText('Görsel kanıt toplama', { exact: true }).first()).toBeVisible();
  expect(requests.find((r) => r.path.endsWith('/captures'))?.body.url).toContain('giris-01.test');
});
test('candidate evidence and submission action are connected', async ({ page }) => {
  const { requests } = await desk(page);
  await page.getByRole('tab', { name: 'Adaylar', exact: true }).click();
  await expect(page.getByText('Ortak JavaScript içeriği', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Başlangıç bulgusu yap', exact: true }).click();
  await expect(page.getByText('Başlangıç bulgusuna eklendi.', { exact: true })).toBeVisible();
  expect(requests.find((r) => r.path.endsWith('/submissions'))?.body).toMatchObject({
    value: 'giris-02.test',
    source: 'analyst_discovery',
  });
  await page.getByRole('button', { name: 'Kaynak kanıtı 1', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toBeVisible();
});
test('selected discovery runs show changed values and approximate history', async ({ page }) => {
  await desk(page);
  await page.getByRole('tab', { name: 'Değişimler', exact: true }).click();
  await expect(page.getByLabel('Önceki çalışma')).toHaveValue('run-1');
  await expect(page.getByLabel('Sonraki çalışma')).toHaveValue('run-2');
  await expect(page.getByText('203.0.113.1', { exact: false })).toBeVisible();
  await expect(page.getByText('203.0.113.2', { exact: false })).toBeVisible();
  await expect(page.getByText('Önceki çalışma yaklaşık olarak yeniden oluşturuldu.')).toBeVisible();
});
test('watch pause, interval, run and alert acknowledgement persist', async ({ page }) => {
  const { watch, alerts, requests } = await desk(page);
  await page.getByRole('tab', { name: 'İzleme', exact: true }).click();
  await page.getByRole('button', { name: 'Duraklat', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Etkinleştir', exact: true })).toBeVisible();
  expect(watch.enabled).toBe(false);
  await page.getByLabel('İzleme aralığı: Başlangıç bulguları').selectOption('360');
  await expect(page.getByLabel('İzleme aralığı: Başlangıç bulguları')).toHaveValue('360');
  await page.getByRole('button', { name: 'Şimdi çalıştır', exact: true }).click();
  await expect.poll(() => requests.some((r) => r.path.endsWith('/watch-1/run'))).toBeTruthy();
  await page.getByRole('button', { name: 'Okundu olarak işaretle', exact: true }).click();
  await expect(page.getByText('Okundu', { exact: true })).toBeVisible();
  expect(alerts[0].read).toBe(true);
});
test('story evidence selection drives masked preview, navigation and HTML download', async ({ page }) => {
  const { requests } = await desk(page);
  await page.getByRole('tab', { name: 'Paylaşım', exact: true }).click();
  await page.getByLabel('Kanıtı seç: browser_capture · giris-01.test').check();
  await page.getByRole('button', { name: 'Önizlemeyi oluştur', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Sunum önizlemesi' })).toContainText('Maskelenmiş gözlem');
  expect(requests.find((r) => r.path.endsWith('/story/preview'))?.body).toEqual({
    evidence_ids: ['ev-1'],
    redact: true,
  });
  await page.getByRole('button', { name: 'Sonraki kart', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Sunum önizlemesi' })).toContainText('DNS gözlemi');
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'HTML sunumunu indir', exact: true }).click();
  expect((await downloaded).suggestedFilename()).toMatch(/\.html$/);
  expect(requests.find((r) => r.path.endsWith('/story/export'))?.body.preview_id).toBe('preview-fixture');
});
test('mobile workbench preserves error, empty and demo states', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await desk(page, true);
  await expect(page.getByRole('button', { name: 'Görüntü al', exact: true })).toBeDisabled();
  await page.route('**/candidates?limit=30', (route) =>
    route.fulfill({ status: 503, json: { error: { message: 'Adaylar alınamadı.' } } }),
  );
  await page.getByRole('tab', { name: 'Adaylar', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Adaylar alınamadı.');
  await page.route('**/candidates?limit=30', (route) =>
    route.fulfill({ json: { items: [], total_unique: 0 } }),
  );
  await page.getByRole('button', { name: 'Yeniden dene' }).click();
  await expect(page.getByText('Henüz sıralanacak aday yok', { exact: true })).toBeVisible();
  for (const tab of ['Görsel kanıt', 'Değişimler', 'İzleme', 'Paylaşım']) {
    await page.getByRole('tab', { name: tab, exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBeFalsy();
  }
});

test('watch target picker reaches domain 101 and retains earlier targets after paginated load', async ({
  page,
}) => {
  const { requests } = await desk(page);
  await page.getByRole('tab', { name: 'İzleme', exact: true }).click();
  const select = page.getByRole('combobox', { name: 'İzlenecek hedef', exact: true });
  await expect(select.locator('option')).toHaveCount(101);
  await expect(page.getByRole('button', { name: 'Daha fazla hedef yükle', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Daha fazla hedef yükle', exact: true }).click();
  await expect(select.locator('option')).toHaveCount(121);
  await expect(select.locator('option[value="entity-1"]')).toHaveCount(1);
  await expect(select.locator('option[value=""]')).toHaveText('Tüm başlangıç bulguları');
  await select.selectOption('entity-101');
  await page.getByRole('button', { name: 'İzleme ekle', exact: true }).click();
  await expect
    .poll(() => requests.find((r) => r.path.endsWith('/watches'))?.body.entity_id)
    .toBe('entity-101');
  await expect(page.getByRole('button', { name: 'Daha fazla hedef yükle', exact: true })).toHaveCount(0);
});
