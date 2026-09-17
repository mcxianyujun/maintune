const { chromium } = require("playwright-core");
const fs = require("node:fs");

const url = process.env.MAINTAINER_SMOKE_URL || "https://maintainer.erichmc.bond";
const tokenFile = process.env.MAINTAINER_ADMIN_TOKEN_FILE;
if (!tokenFile) throw new Error("Set MAINTAINER_ADMIN_TOKEN_FILE");
const token = fs.readFileSync(tokenFile, "utf8").trim();
const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean).find(fs.existsSync);
if (!executablePath) throw new Error("Chrome was not found");

(async () => {
  const browser = await chromium.launch({ executablePath, headless: true, args: ["--no-proxy-server", "--disable-extensions", "--disable-background-networking"] });
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  const consoleErrors = [], failedRequests = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText || "failed"}`));
  page.on("response", (response) => { if (response.status() >= 400) failedRequests.push(`${response.url()} HTTP ${response.status()}`); });
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
    await page.getByLabel("管理员访问令牌").fill(token);
    await page.getByRole("button", { name: /进入控制台/ }).click();
    await page.getByRole("heading", { name: "概览" }).waitFor();

    await page.getByRole("button", { name: "系统设置" }).click();
    const modelBefore = await page.getByLabel("模型").inputValue();
    await page.getByRole("button", { name: "保存设置" }).click();
    await page.getByText("主 Agent 设置已保存", { exact: true }).waitFor();
    if (await page.getByLabel("模型").inputValue() !== modelBefore) throw new Error("Main model changed during round-trip");

    await page.getByRole("button", { name: "模型" }).click();
    const modelTag = (await page.locator(".model-tag").first().innerText()).trim();
    await page.getByRole("button", { name: "编辑", exact: true }).first().click();
    await page.getByRole("heading", { name: "编辑供应商" }).waitFor();
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByText("供应商已保存", { exact: true }).waitFor();
    if ((await page.locator(".model-tag").first().innerText()).trim() !== modelTag) throw new Error("Provider model changed during round-trip");

    await page.getByRole("button", { name: "Agents" }).click();
    const agentCard = page.locator(".agent-cards section").filter({ hasText: "ci_analyzer" });
    await agentCard.getByRole("button", { name: "编辑代理" }).click();
    await page.getByRole("heading", { name: "编辑子代理" }).waitFor();
    await page.locator(".effective-config").waitFor();
    await page.getByRole("button", { name: "保存代理" }).click();
    await page.getByText("子代理已保存", { exact: true }).waitFor();

    await page.getByRole("button", { name: "运行记录" }).click();
    await page.getByLabel("诊断输入").fill("Reply with exactly: diagnostic-ok");
    await page.getByRole("button", { name: /运行诊断/ }).click();
    const dialog = page.locator(".modal").filter({ hasText: "运行详情" });
    await dialog.getByText("已完成", { exact: true }).waitFor({ timeout: 180_000 });
    const result = (await dialog.locator("pre").innerText()).trim();
    if (!result.toLowerCase().includes("diagnostic-ok")) throw new Error("Diagnostic response did not contain the expected marker");
    if (consoleErrors.length || failedRequests.length) throw new Error(JSON.stringify({ consoleErrors, failedRequests }));
    console.log(JSON.stringify({ url, settingsRoundTrip: true, providerRoundTrip: true, agentRoundTrip: true, diagnostic: "completed", diagnosticMarker: true, consoleErrors, failedRequests }));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error.stack || error.message); process.exit(1); });

