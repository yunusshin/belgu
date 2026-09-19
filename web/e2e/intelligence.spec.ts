import { test, expect } from '@playwright/test';
import { installApiFixtures } from './fixtures';

const at = '2026-09-01T10:00:00Z';
const ref = {
  investigation_id: 'case-1',
  evidence_id: 'ev-1',
  subject: { kind: 'domain', value: 'giris-01.test' },
  kind: 'javascript_content',
  provider: 'page',
  source_ref: 'https://source.test/app.js',
  observed_at: at,
  retrieved_at: at,
};
const historical = { ...ref, investigation_id: 'older-case', evidence_id: 'old-1' };
const item = {
  investigation_id: 'older-case',
  title: 'Önceki inceleme',
  brand_name: 'Örnek marka',
  workflow: 'closed',
  disposition: 'benign',
  decision: { value: 'benign', note: 'Tedarikçi doğrulandı.', created_at: at },
  score: 30,
  priority: 'high',
  reasons: [
    {
      kind: 'javascript',
      value: 'a'.repeat(64),
      label: 'Aynı JavaScript içerik özeti',
      weight: 30,
      discounted: false,
      detail: 'Araştırma ipucu.',
      evidence_refs: [ref, historical],
    },
  ],
  evidence_refs: [ref, historical],
};
const turn = {
  id: 'turn-1',
  investigation_id: 'case-1',
  message: 'Hangi kanıtı incelemeliyim?',
  created_at: at,
  answer: 'Kaynakları karşılaştırabilirsiniz.',
  claims: [{ text: 'Betik özeti kayıtta mevcut.', kind: 'observation', evidence_refs: [ref] }],
  actions: [{ type: 'apply_filters', label: 'Betik gruplarını incele', filters: { shared: 'javascript' } }],
  uncertainties: ['Atıf sağlamaz.'],
  model: {
    id: 'recorded-demo',
    recorded_demo: true,
    prompt_version: 'assistant-v1',
    runtime_version: null,
    input_tokens: null,
    output_tokens: null,
  },
  snapshot: {
    id: 'snapshot-1',
    evidence_refs: [ref],
    omissions: {
      retrieval_capped: false,
      context_evidence: 0,
      history_capped: false,
      token_budget_evidence: 0,
      token_budget_history: 0,
      memory_cases_omitted: 0,
    },
  },
};

test('memory preserves decision context and exposes both source scopes', async ({ page }) => {
  await installApiFixtures(page);
  await page.route('**/memory?*', (route) =>
    route.fulfill({
      json: {
        items: [item],
        total_unique: 1,
        next_cursor: null,
        coverage: {
          truncated: false,
          cases_scanned: 1,
          current_observations_scanned: 1,
          foreign_observations_scanned: 1,
        },
        limitations: ['Atıf veya zararlılık olasılığı değildir.'],
      },
    }),
  );
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'İnceleme hafızası', exact: true }).click();
  await expect(page.getByText('Tedarikçi doğrulandı.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Önceki kanıtı aç', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Güncel kanıtı aç', exact: true })).toBeVisible();
});

test('assistant retains conversation after reload and offers retry on local failure', async ({ page }) => {
  await installApiFixtures(page);
  let saved = false;
  let fail = true;
  await page.route('**/assistant*', async (route) => {
    if (route.request().method() === 'GET')
      return route.fulfill({ json: { items: saved ? [turn] : [], next_cursor: null } });
    expect(route.request().postDataJSON()).toEqual({ message: turn.message, evidence_ids: [] });
    if (fail) {
      fail = false;
      return route.fulfill({
        status: 503,
        json: { error: { message: 'Yerel model yanıt veremedi. Yeniden deneyin.', retryable: true } },
      });
    }
    saved = true;
    return route.fulfill({ status: 201, json: turn });
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Araştırma asistanı', exact: true }).click();
  await page.getByRole('textbox', { name: 'Araştırma sorusu', exact: true }).fill(turn.message);
  await page.getByRole('button', { name: 'Sor', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Yerel model yanıt veremedi');
  await page.getByRole('button', { name: 'Yeniden dene', exact: true }).click();
  await expect(page.getByText(turn.answer)).toBeVisible();
  await expect(page.getByText('Kayıtlı demo yanıtı', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(turn.answer)).toBeVisible();
  await page.getByRole('button', { name: 'Betik gruplarını incele', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Araştırma', exact: true })).toBeVisible();
});

test('selected board evidence and retry retain the original submitted context', async ({ page }) => {
  await installApiFixtures(page);
  await page.addInitScript(() =>
    localStorage.setItem('belgu:case-workspace:v1:case-1:evidence-board', JSON.stringify(['ev-1'])),
  );
  const requests: unknown[] = [];
  await page.route('**/assistant*', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { items: [], next_cursor: null } });
    requests.push(route.request().postDataJSON());
    if (requests.length === 1)
      return route.fulfill({ status: 503, json: { error: { message: 'Model kullanılamıyor.' } } });
    return route.fulfill({ status: 201, json: turn });
  });
  await page.goto('/#/investigations/case-1');
  await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
  await page.getByRole('tab', { name: 'Araştırma asistanı', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Panodaki kanıtları kullan' }).check();
  await page.getByRole('textbox', { name: 'Araştırma sorusu', exact: true }).fill(turn.message);
  await page.getByRole('button', { name: 'Sor', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.getByRole('checkbox', { name: 'Panodaki kanıtları kullan' }).uncheck();
  await page.getByRole('textbox', { name: 'Araştırma sorusu', exact: true }).fill('Başka soru');
  await page.getByRole('button', { name: 'Yeniden dene', exact: true }).click();
  await expect(page.getByText(turn.answer)).toBeVisible();
  expect(requests).toEqual([
    { message: turn.message, evidence_ids: ['ev-1'] },
    { message: turn.message, evidence_ids: ['ev-1'] },
  ]);
});
