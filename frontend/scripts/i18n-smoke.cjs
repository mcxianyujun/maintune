const { chromium } = require("playwright-core");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const output = path.join(root, "test-results", "i18n");
const state = path.join(output, "state");
const token = "i18n-smoke-admin-token-0000000000000001";
const port = 18775;
const python = process.env.PYTHON_PATH || path.join(root, ".venv", "Scripts", "python.exe");
const chrome = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
fs.rmSync(output, { recursive: true, force: true });
fs.mkdirSync(state, { recursive: true });

function waitFor(url, timeout = 30000) {
  const end = Date.now() + timeout;
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try { const response = await fetch(url); if (response.ok) return resolve(); } catch {}
      if (Date.now() >= end) return reject(new Error(`Timed out waiting for ${url}`));
      setTimeout(poll, 200);
    };
    poll();
  });
}

(async () => {
  const backend = spawn(python, ["-m", "uvicorn", "maintainer.api:create_app", "--factory", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, MAINTAINER_ADMIN_TOKEN: token, MAINTAINER_ENCRYPTION_KEY: "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=", MAINTAINER_DATABASE_URL: `sqlite:///${path.join(state, "maintainer.db").replaceAll("\\", "/")}`, MAINTAINER_WORKSPACE_ROOT: path.join(state, "workspaces"), MAINTAINER_STATIC_DIR: path.join(root, "frontend", "dist") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let log = "";
  backend.stdout.on("data", chunk => log += chunk.toString());
  backend.stderr.on("data", chunk => log += chunk.toString());
  let browser;
  try {
    await waitFor(`http://127.0.0.1:${port}/healthz`);
    browser = await chromium.launch({ executablePath: chrome, headless: true, args: ["--no-proxy-server", "--disable-extensions", "--disable-background-networking"] });
    for (const test of [
      { locale: "zh-CN", viewport: {width: 1440, height: 900}, tokenLabel: "管理员访问令牌", enter: "进入控制台 →", heading: "概览", nav: "系统设置", dialog: "首次运行设置向导", file: "desktop-zh-CN.png" },
      { locale: "en-US", viewport: {width: 1440, height: 900}, tokenLabel: "Administrator access token", enter: "Open console →", heading: "Overview", nav: "System Settings", dialog: "First-run Setup Wizard", file: "desktop-en-US.png" },
      { locale: "zh-CN", viewport: {width: 390, height: 844}, tokenLabel: "管理员访问令牌", enter: "进入控制台 →", heading: "概览", nav: "系统设置", dialog: "首次运行设置向导", file: "mobile-zh-CN.png" },
      { locale: "en-US", viewport: {width: 390, height: 844}, tokenLabel: "Administrator access token", enter: "Open console →", heading: "Overview", nav: "System Settings", dialog: "First-run Setup Wizard", file: "mobile-en-US.png" },
    ]) {
      const context = await browser.newContext({ viewport: test.viewport, serviceWorkers: "block" });
      await context.addInitScript(locale => localStorage.setItem("maintainer.locale", locale), test.locale);
      const page = await context.newPage();
      const errors = [];
      page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(`http://127.0.0.1:${port}`, { waitUntil: "networkidle" });
      if (test.locale === "en-US" && await page.getByText("Connect a model, sandbox, and repository to get started.").count() !== 1) throw new Error("English Hero subtitle is missing");
      await page.getByLabel(test.tokenLabel).fill(token);
      await page.getByRole("button", {name: test.enter}).click();
      await page.getByRole("dialog", {name: test.dialog}).waitFor();
      await page.locator(".wizard-steps button.text").evaluate(button => button.click());
      await page.getByRole("heading", {name: test.heading}).waitFor();
      await page.screenshot({path: path.join(output, `overview-${test.file}`), fullPage: true});
      await page.locator("nav button").filter({hasText: test.nav}).first().click();
      await page.locator(".page-title").getByRole("heading", {name: test.nav}).waitFor();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      if (overflow) throw new Error(`${test.locale} overflows at ${test.viewport.width}px`);
      await page.screenshot({path: path.join(output, test.file), fullPage: true});
      if (errors.length) throw new Error(`${test.locale} browser errors: ${JSON.stringify(errors)}`);
      await context.close();
    }

    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${port}`);
    await page.evaluate(() => localStorage.setItem("maintainer.locale", "en-US"));
    await page.reload();
    await page.getByRole("button", {name: "简体中文"}).click();
    await page.waitForFunction(() => document.documentElement.lang === "zh-CN");
    await page.reload();
    if (await page.evaluate(() => localStorage.getItem("maintainer.locale")) !== "zh-CN") throw new Error("Language preference did not persist");
    if (await page.evaluate(() => document.documentElement.lang) !== "zh-CN") throw new Error("Persisted language was not restored");
    await context.close();
    console.log(JSON.stringify({locales: ["zh-CN", "en-US"], desktop: true, mobile: true, persistence: true, screenshots: fs.readdirSync(output).filter(name => name.endsWith(".png"))}));
  } finally {
    if (browser) await browser.close();
    backend.kill();
  }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
