import { expect, test, type Page } from '@playwright/test';
import { installApiFixtures } from './fixtures';

async function intelligenceFixtures(page: Page) {
  const { caseData } = await installApiFixtures(page);
  caseData.attachments.push({ id: 'active-image', mime: 'image/png' } as never);
  const refs = [
    {
      investigation_id: 'case-1',
      evidence_id: 'current-js',
      subject: { kind: 'domain', value: 'current-private.test' },
      kind: 'javascript_content',
      provider: 'page',
      source_ref: 'https://current-private.test/app.js',
      observed_at: '2026-09-12T10:00:00Z',
      retrieved_at: '2026-09-12T10:01:00Z',
      payload: { js_sha256: 'a'.repeat(64) },
    },
    {
      investigation_id: 'case-old',
      evidence_id: 'older-js',
      subject: { kind: 'domain', value: 'older-private.test' },
      kind: 'javascript_content',
      provider: 'historical-source',
      source_ref: 'https://older-private.test/app.js',
      observed_at: '2026-08-12T10:00:00Z',
      retrieved_at: '2026-08-12T10:01:00Z',
      payload: { js_sha256: 'a'.repeat(64) },
    },
  ];
  const previous = {
    ...caseData,
    id: 'case-old',
    title: 'Geçmiş marka incelemesi',
    brand_name: 'Önceki Marka',
    workflow: 'closed',
    disposition: 'needs_review',
    attachments: [{ id: 'historical-image', mime: 'image/png' }],
  };
  const requests: string[] = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname;
    requests.push(url.pathname + url.search);
    if (path === '/api/investigations/case-old') return route.fulfill({ json: previous });
    if (path === '/api/investigations/case-old/evidence/older-js')
      return route.fulfill({
        json: {
          id: 'older-js',
          investigation_id: 'case-old',
          kind: 'javascript_content',
          provider: 'historical-source',
          subject: { kind: 'domain', value: 'older-private.test' },
          source_ref: 'https://older-private.test/app.js',
          observed_at: '2026-08-12T10:00:00Z',
          retrieved_at: '2026-08-12T10:01:00Z',
          payload: { js_sha256: 'a'.repeat(64), note: 'Önceki incelemenin gerçek kapsamı' },
        },
      });
    if (path.endsWith('/assistant')) {
      if (route.request().method() === 'GET')
        return route.fulfill({ json: { items: [], total_unique: 0, next_cursor: null } });
      return route.fulfill({
        json: {
          id: 'turn-1',
          investigation_id: 'case-1',
          answer: 'Önceki incelemedeki betik kaydını karşılaştırabilirsiniz.',
          claims: [
            { text: 'İki kayıt aynı betik özetini taşıyor.', kind: 'observation', evidence_refs: refs },
          ],
          actions: [
            {
              type: 'open_evidence',
              label: 'Önceki kaydı aç',
              investigation_id: 'case-old',
              evidence_id: 'older-js',
            },
            {
              type: 'apply_filters',
              label: 'Görseli olan yeni adayları göster',
              filters: {
                hasCapture: true,
                recent: true,
                sort: 'priority',
                shared: 'javascript',
                kind: 'domain',
                q: '',
              },
            },
          ],
          uncertainties: ['Ortak betik aynı saldırganı kanıtlamaz.'],
          model: {
            recorded_demo: true,
            id: 'recorded-fixture',
            prompt_version: 'assistant-v1',
            runtime_version: null,
            input_tokens: null,
            output_tokens: null,
          },
          snapshot: {
            id: 'snapshot-1',
            evidence_refs: refs,
            omissions: {
              retrieval_capped: false,
              context_evidence: 0,
              history_capped: false,
              token_budget_evidence: 0,
              token_budget_history: 0,
              memory_cases_omitted: 0,
            },
          },
          message: 'Bu kayıtların bağlantısı nedir?',
          created_at: '2026-09-12T10:00:00Z',
        },
      });
    }
    return route.fallback();
  });
  await page.goto('/#/investigations/case-1');
  await expect(page.getByRole('heading', { name: caseData.title })).toBeVisible();
  // Research is deliberately visited before the assistant applies a filter.
  await expect(page.getByRole('button', { name: 'Araştırma', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.locator('.cluster').first().click();
  await expect.poll(() => requests.some((path) => path.includes('group_key=js-0'))).toBe(true);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Araştırma asistanı', exact: true }).click();
  await page.getByRole('textbox', { name: 'Araştırma sorusu' }).fill('Bu kayıtların bağlantısı nedir?');
  await page.getByRole('button', { name: 'Sor', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Önceki kaydı aç', exact: true })).toBeVisible();
  return { requests, caseData };
}

test('foreign source stays scoped while the active case and assistant remain open', async ({ page }) => {
  const { requests, caseData } = await intelligenceFixtures(page);
  const source = page.getByRole('button', { name: 'Önceki kaydı aç', exact: true });
  await source.click();
  await expect(page.getByRole('region', { name: 'Kanıt ayrıntıları' })).toContainText(
    'Önceki incelemenin gerçek kapsamı',
  );
  await expect(page.getByRole('heading', { name: caseData.title })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Araştırma asistanı', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(page.getByRole('button', { name: 'Kanıtı panoya sabitle', exact: true })).toBeDisabled();
  expect(requests).toContain('/api/investigations/case-old/evidence/older-js');
  expect(requests).not.toContain('/api/investigations/case-1/evidence/older-js');
  const image = page.locator('.inspector .attachment-grid img');
  await expect(image).toHaveAttribute('src', '/api/investigations/case-old/attachments/historical-image');
  await page.getByRole('button', { name: 'Ekran görüntüsünü büyüt', exact: true }).click();
  await expect(page.locator('.attachment-full')).toHaveAttribute(
    'src',
    '/api/investigations/case-old/attachments/historical-image',
  );
  await page.getByRole('button', { name: 'Kapat', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(source).toBeFocused();
});

test('assistant filter proposal updates already mounted research and clears a prior group', async ({
  page,
}) => {
  const { requests } = await intelligenceFixtures(page);
  await page.getByRole('button', { name: 'Görseli olan yeni adayları göster', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Araştırma', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect
    .poll(() =>
      requests.some((path) => {
        const url = new URL(path, 'http://fixture');
        return (
          url.pathname.endsWith('/entities') &&
          url.searchParams.get('has_capture') === 'true' &&
          url.searchParams.get('recent_hours') === '24' &&
          url.searchParams.get('sort') === 'priority' &&
          url.searchParams.get('shared') === 'javascript' &&
          !url.searchParams.has('group_key')
        );
      }),
    )
    .toBe(true);
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Görseli olan yeni adayları göster', exact: true }),
  ).toBeVisible();
});
