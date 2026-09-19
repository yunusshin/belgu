import { defineConfig } from '@playwright/test';
import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
const browserCache = join(homedir(), '.cache/ms-playwright');
const cachedBrowser = existsSync(browserCache)
  ? readdirSync(browserCache)
      .filter((name) => /^chromium-\d+$/.test(name))
      .sort()
      .reverse()
      .flatMap((name) =>
        ['chrome-linux/chrome', 'chrome-linux64/chrome'].map((binary) => join(browserCache, name, binary)),
      )
      .find(existsSync)
  : undefined;
export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5174',
    headless: true,
    viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || cachedBrowser },
    screenshot: 'only-on-failure',
  },
  webServer: [
    { command: 'npm run dev', url: 'http://127.0.0.1:5174', reuseExistingServer: true },
    {
      command: '../.venv/bin/python e2e/start_api.py --port 8775 --mode demo',
      url: 'http://127.0.0.1:8775/api/health',
      reuseExistingServer: !process.env.CI,
    },
    {
      command: '../.venv/bin/python e2e/start_api.py --port 8776 --mode operational',
      url: 'http://127.0.0.1:8776/api/health',
      reuseExistingServer: !process.env.CI,
    },
  ],
  projects: [
    {
      name: 'fixtures',
      testMatch:
        /(?:workspace|workbench|research-explorer|image-comparison|intelligence|visual-intelligence|replay).spec.ts/,
    },
    { name: 'integrated', testMatch: /integrated.spec.ts/ },
  ],
});
