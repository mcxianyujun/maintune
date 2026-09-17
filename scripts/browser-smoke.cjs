const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const token = process.env.MAINTAINER_TOKEN_FILE ? fs.readFileSync(process.env.MAINTAINER_TOKEN_FILE, 'utf8').trim() : fs.readFileSync('.env', 'utf8').match(/^MAINTAINER_ADMIN_TOKEN=(.+)$/m)[1].trim();
  const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_EXECUTABLE ? {executablePath: process.env.BROWSER_EXECUTABLE} : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(process.env.MAINTAINER_TEST_URL || 'http://127.0.0.1:8000');
    await page.getByLabel('管理员访问令牌').fill(token);
    await page.getByRole('button', { name: /进入控制台/ }).click();
    await page.getByRole('heading', { name: '概览', exact: true }).waitFor();
    fs.mkdirSync('test-results', { recursive: true });
    await page.screenshot({ path: path.resolve('test-results/dashboard.png'), fullPage: true });
    await page.getByRole('button', { name: '模型供应商', exact: false }).first().click();
    await page.getByRole('button', { name: '＋ 添加供应商', exact: true }).click();
    await page.getByLabel('名称', { exact: true }).fill('Browser smoke fixture');
    await page.getByLabel('Base URL（含 /v1 等 API 前缀）').fill('https://example.invalid/v1');
    await page.getByLabel('API Key / Replace Key').fill('browser-test-not-a-real-secret');
    await page.getByLabel('模型列表（每行一个）').fill('test-model');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.getByRole('heading', { name: 'Browser smoke fixture' }).waitFor();
    if ((await page.locator('body').innerText()).includes('browser-test-not-a-real-secret')) throw new Error('Secret exposed');
    page.once('dialog', dialog => dialog.accept());
    const card = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Browser smoke fixture' }) });
    await card.getByRole('button', { name: '删除', exact: true }).click();
    await page.getByRole('heading', { name: 'Browser smoke fixture' }).waitFor({ state: 'detached' });
    await page.getByRole('button', { name: '系统设置', exact: false }).first().click();
    await page.getByRole('button', { name: '测试已保存配置' }).click();
    await page.getByRole('status').filter({ hasText: '测试成功' }).waitFor();
    await page.getByRole('button', { name: '子代理', exact: false }).first().click();
    await page.getByRole('heading', { name: 'Issue 分析' }).waitFor();
    await page.screenshot({ path: path.resolve('test-results/agents.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.resolve('test-results/mobile.png'), fullPage: true });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Mobile horizontal overflow');
    if (errors.length) throw new Error(errors.join('\n'));
    console.log('Browser smoke passed: login, provider CRUD, masked key, sandbox probe, agents, mobile; no console errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
