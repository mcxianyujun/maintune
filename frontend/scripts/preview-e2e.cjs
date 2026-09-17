const { chromium } = require("playwright-core");
const { createServer } = require("node:http");
const { generateKeyPairSync } = require("node:crypto");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const output = path.join(root, "test-results", "preview");
const state = path.join(output, "fresh-state");
const adminToken = "preview-e2e-admin-token-0000000000000001";
const encryptionKey = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=";
const appPort = 18765;
const mockPort = 18766;
const python = process.env.PYTHON_PATH || path.join(root, ".venv", "Scripts", "python.exe");
const chrome = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
let backendLog = "";

fs.rmSync(output, { recursive: true, force: true });
fs.mkdirSync(state, { recursive: true });

const mock = createServer((request, response) => {
  response.setHeader("content-type", "application/json");
  if (request.url === "/v1/models") return response.end(JSON.stringify({ data: [{ id: "preview-model" }] }));
  if (request.url === "/app/installations") return response.end(JSON.stringify([{ id: 42, account: { login: "preview-test" } }]));
  response.statusCode = 404;
  response.end(JSON.stringify({ message: "not found" }));
});

function waitFor(url, timeout = 30000) {
  const end = Date.now() + timeout;
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try { const response = await fetch(url); if (response.ok) return resolve(response); } catch {}
      if (Date.now() >= end) return reject(new Error(`Timed out waiting for ${url}`));
      setTimeout(poll, 200);
    };
    poll();
  });
}

(async () => {
  await new Promise(resolve => mock.listen(mockPort, "127.0.0.1", resolve));
  console.log("preview-e2e: mock ready");
  const backend = spawn(python, ["-m", "uvicorn", "maintainer.api:create_app", "--factory", "--host", "127.0.0.1", "--port", String(appPort)], {
    cwd: root,
    env: {
      ...process.env,
      MAINTAINER_ADMIN_TOKEN: adminToken,
      MAINTAINER_ENCRYPTION_KEY: encryptionKey,
      MAINTAINER_DATABASE_URL: `sqlite:///${path.join(state, "maintainer.db").replaceAll("\\", "/")}`,
      MAINTAINER_WORKSPACE_ROOT: path.join(state, "workspaces"),
      MAINTAINER_STATIC_DIR: path.join(root, "frontend", "dist"),
      OH_PERSISTENCE_DIR: path.join(state, "openhands"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  backend.stdout.on("data", chunk => { backendLog += chunk.toString(); });
  backend.stderr.on("data", chunk => { backendLog += chunk.toString(); });
  let browser;
  try {
    await waitFor(`http://127.0.0.1:${appPort}/healthz`, 45000);
    console.log("preview-e2e: app healthy");
    const keys = generateKeyPairSync("rsa", { modulusLength: 2048, privateKeyEncoding: { type: "pkcs8", format: "pem" }, publicKeyEncoding: { type: "spki", format: "pem" } });
    browser = await chromium.launch({ executablePath: chrome, headless: true, args: ["--no-proxy-server", "--disable-extensions", "--disable-background-networking"] });
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("maintainer.locale", "zh-CN"));
    const page = await context.newPage();
    const consoleErrors = [], failedRequests = [];
    page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("pageerror", error => consoleErrors.push(error.message));
    page.on("requestfailed", request => failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || "failed"}`));
    page.on("response", response => { if (response.status() >= 400) failedRequests.push(`${response.request().method()} ${response.url()} HTTP ${response.status()}`); });

    await page.goto(`http://127.0.0.1:${appPort}`, { waitUntil: "networkidle" });
    console.log("preview-e2e: browser loaded");
    await page.getByLabel("管理员访问令牌").fill(adminToken);
    await page.getByRole("button", { name: "进入控制台 →" }).click();
    await page.getByRole("dialog", { name: "首次运行设置向导" }).waitFor();
    console.log("preview-e2e: wizard opened");
    await page.screenshot({ path: path.join(output, "setup-wizard-desktop.png"), fullPage: true });
    await page.getByRole("button", { name: "开始配置 →" }).click();
    await page.getByRole("button", { name: "环境已就绪，继续" }).click();
    await page.getByLabel("Provider 名称").fill("Preview E2E");
    await page.getByLabel("Base URL").fill(`http://127.0.0.1:${mockPort}/v1`);
    await page.getByLabel("API Key").fill("ephemeral-diagnostic-key");
    await page.getByLabel("Model ID").fill("preview-model");
    await page.getByRole("button", { name: "保存并继续" }).click();
    await page.getByText("03 / GITHUB APP").waitFor();
    await page.getByLabel("App ID").fill("1");
    await page.getByLabel("Installation ID（可选）").fill("42");
    await page.getByLabel("GitHub API URL").fill(`http://127.0.0.1:${mockPort}`);
    await page.getByLabel("Private key PEM").fill(keys.privateKey);
    await page.getByLabel("Webhook Secret").fill("ephemeral-webhook-secret");
    await page.getByRole("button", { name: "保存并继续" }).click();
    await page.getByText("04 / SANDBOX").waitFor();
    await page.getByRole("button", { name: "保存、测试并继续" }).click();
    await Promise.race([
      page.getByText("05 / REPOSITORY").waitFor(),
      page.getByRole("alert").waitFor().then(async () => { throw new Error(`Sandbox step failed: ${await page.getByRole("alert").innerText()}`); }),
    ]);
    await page.getByLabel("owner/repository").fill("preview/testbed");
    await page.getByLabel("测试命令").fill("npm test");
    await page.getByRole("button", { name: "保存并继续" }).click();
    await page.getByRole("button", { name: "暂时跳过" }).click();
    await page.getByText("07 / DIAGNOSTICS").waitFor();
    await page.getByRole("button", { name: "运行全部诊断" }).click();
    await page.getByText("SETUP COMPLETE").waitFor({ timeout: 45000 });
    console.log("preview-e2e: diagnostics passed");
    await page.getByRole("button", { name: "进入概览 →" }).click();
    await page.getByRole("dialog", { name: "首次运行设置向导" }).waitFor({ state: "detached" });
    await page.getByRole("heading", { name: "概览" }).waitFor();
    const theme = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--brand").trim().toLowerCase());
    if (theme !== "#66ccff") throw new Error(`Unexpected primary theme color: ${theme}`);
    if (await page.locator(".brand-mark svg").count() !== 1) throw new Error("Brand mark is not rendered");
    if (await page.locator("nav .nav-mascot").count() !== 10) throw new Error("Semantic mascot navigation set is incomplete");
    if (await page.locator(".dashboard-hero .mascot-scene").count() !== 1) throw new Error("Dashboard theme illustration is missing");
    const faviconHref = await page.locator('link[rel="icon"]').getAttribute("href");
    const faviconResponse = await page.request.get(new URL(faviconHref, page.url()).href);
    if (!faviconResponse.ok()) throw new Error(`Favicon failed: HTTP ${faviconResponse.status()}`);
    await page.screenshot({ path: path.join(output, "dashboard-desktop.png"), fullPage: true });

    for (const label of ["GitHub 接入", "仓库", "维护任务", "模型供应商", "子代理", "工作环境", "插件与扩展", "运行记录", "系统设置", "概览"]) {
      await page.locator("nav button").filter({ hasText: label }).first().click();
      await page.locator(".page-title").getByRole("heading", { name: label }).waitFor();
    }
    for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(150);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      if (overflow) {
        const widest = await page.evaluate(() => [...document.querySelectorAll("body *")].map(element => ({ tag: element.tagName, cls: element.className, width: element.getBoundingClientRect().width, right: element.getBoundingClientRect().right, scrollWidth: element.scrollWidth })).filter(item => item.right > document.documentElement.clientWidth + 1 || item.scrollWidth > document.documentElement.clientWidth + 1).sort((a,b) => b.right - a.right).slice(0,8));
        throw new Error(`Body overflows horizontally at ${viewport.width}px: ${JSON.stringify(widest)}`);
      }
    }
    const touchTargets = await page.locator("nav button").evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().height));
    if (touchTargets.some(height => height < 44)) throw new Error(`Mobile navigation touch target below 44px: ${JSON.stringify(touchTargets)}`);
    await page.screenshot({ path: path.join(output, "dashboard-mobile.png"), fullPage: true });
    if (consoleErrors.length || failedRequests.length) throw new Error(JSON.stringify({ consoleErrors, failedRequests }, null, 2));
    console.log(JSON.stringify({ setupComplete: true, theme, brandMark: true, mascotNavigation: 10, dashboardIllustration: true, pagesChecked: 10, viewports: [1920, 1280, 390], consoleErrors, failedRequests, screenshots: ["setup-wizard-desktop.png", "dashboard-desktop.png", "dashboard-mobile.png"] }));
  } finally {
    if (browser) await browser.close();
    backend.kill();
    mock.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  if (backendLog) console.error(backendLog.replace(/Bearer\s+\S+/gi, "Bearer [REDACTED]"));
  process.exitCode = 1;
});
