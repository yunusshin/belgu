import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { installApiFixtures } from './fixtures';

for (const width of [390, 1440])
  test(`profile pair, ranking and failure evidence at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await installApiFixtures(page, { demo: false });
    const png = readFileSync('../src/belgu/demo/assets/fictional-login.png');
    const image = (id: string) => `/api/${id}.png`;
    const captures = ['desktop', 'mobile', 'desktop'].map((profile, index) => ({
      id: `capture-${index}`,
      evidence_id: `capture-${index}`,
      profile,
      image_url: image(index === 2 ? 'third' : profile),
      url: `https://fixture.test/${profile}`,
      final_url: `https://fixture.test/${profile}`,
      observed_at: '2026-09-12T10:00:00Z',
      retrieved_at: '2026-09-12T10:00:01Z',
      artifact_id: profile,
      viewport: profile === 'mobile' ? { width: 390, height: 844 } : { width: 1365, height: 900 },
      text: `${profile} DOM observation`,
      forms: [],
      ocr_status: 'unavailable',
      ocr_text: '',
    }));
    const requests: string[] = [];
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('.png')) return route.fulfill({ body: png, contentType: 'image/png' });
      if (path.endsWith('/captures') && route.request().method() === 'POST') {
        requests.push(route.request().postDataJSON().profile);
        return route.fulfill({
          json: {
            id: `job-${requests.length}`,
            kind: 'capture',
            status: 'queued',
            investigation_id: 'case-1',
          },
        });
      }
      if (path.endsWith('/captures'))
        return route.fulfill({
          json: {
            items: captures,
            references: [
              { id: 'reference', image_url: image('reference'), created_at: '2026-09-12T09:00:00Z' },
            ],
            failures: [
              { evidence_id: 'failed-1', profile: 'mobile', reason: 'Fixture offline', status: 'failed' },
            ],
            capabilities: { status: 'ready', message: 'Ready', ocr_available: false },
          },
        });
      if (path.endsWith('/visual-similarity')) {
        const referenceId = new URL(route.request().url()).searchParams.get('reference_id');
        const ranked = referenceId === 'capture-1' ? captures[2] : captures[0];
        return route.fulfill({
          json: {
            method_version: 'local-phash-edge-rgb-v1',
            reference: { id: 'reference' },
            items: [
              {
                ...ranked,
                score: 94,
                evidence_ids: [ranked.id],
                components: { perceptual: 95, structure: 91, color: 97 },
              },
            ],
            unassessed: [{ ...captures[1], reason: 'incompatible_geometry' }],
            coverage: { captures: 2, assessed_unique: 1, unassessed: 1, duplicates: 0 },
            limitations: [],
          },
        });
      }
      return route.fallback();
    });
    await page.goto('/#/investigations/case-1');
    await page.getByRole('button', { name: 'Çalışma masası', exact: true }).click();
    await expect(page.getByText('Fixture offline', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Yerel görsel sıralama' })).toBeVisible();
    await page.getByRole('button', { name: 'Görüntüleri aç', exact: true }).click();
    await expect(page.getByAltText('Yakalanan sayfa', { exact: true })).toHaveAttribute(
      'src',
      image('desktop'),
    );
    await expect(page.getByAltText('Marka referansı', { exact: true })).toHaveAttribute(
      'src',
      image('reference'),
    );
    await page.getByRole('button', { name: 'İki gözlem', exact: true }).click();
    await expect(page.getByAltText('İkinci gözlem', { exact: true })).toHaveAttribute('src', image('mobile'));
    await page.getByRole('button', { name: 'Görüntüleri aç', exact: true }).click();
    await expect(page.getByAltText('Yakalanan sayfa', { exact: true })).toHaveAttribute(
      'src',
      image('third'),
    );
    await expect(page.getByAltText('İkinci gözlem', { exact: true })).toHaveAttribute('src', image('mobile'));
    await page.getByLabel('İkinci gözlem', { exact: true }).selectOption('capture-1');
    await expect(page.getByAltText('İkinci gözlem', { exact: true })).toHaveAttribute('src', image('mobile'));
    await expect(page.getByText('mobile DOM observation', { exact: true })).toBeVisible();
    await expect(page.getByText(/Farklı profil veya görünüm alanı/)).toBeVisible();
    await page
      .getByRole('region', { name: 'Gözlem farkları', exact: true })
      .screenshot({ path: testInfo.outputPath('observation-pair.png') });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
    await page.getByLabel('Yakalama profili').selectOption('both');
    await page.getByRole('button', { name: 'İki profili yakala', exact: true }).click();
    await expect.poll(() => requests).toEqual(['desktop', 'mobile']);
  });
