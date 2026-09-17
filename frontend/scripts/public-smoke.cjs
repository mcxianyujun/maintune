const { chromium } = require("playwright-core");
const fs = require("node:fs");

const url = process.env.MAINTAINER_SMOKE_URL || "https://maintainer.erichmc.bond";
const candidates = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);
const executablePath = candidates.find((path) => fs.existsSync(path));
if (!executablePath) throw new Error("Set CHROME_PATH to an installed Chromium browser");

(async () => {
  const browser = await chromium.launch({
    executablePath,
    headless: true,
    args: ["--no-proxy-server", "--disable-extensions", "--disable-background-networking"],
  });
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText || "failed"}`));
  page.on("response", (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.url()} HTTP ${response.status()}`);
  });
  try {
    const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
    if (!response || response.status() !== 200) throw new Error(`Document returned ${response?.status()}`);
    await page.getByLabel("管理员访问令牌").waitFor({ state: "visible", timeout: 10_000 });
    await page.getByRole("button", { name: /进入控制台/ }).waitFor({ state: "visible" });
    await page.getByText("接入模型、沙箱和仓库后，就可以开始维护。", { exact: true }).waitFor({ state: "visible" });
    const rootText = (await page.locator("#root").innerText()).trim();
    if (!rootText.includes("Maintainer")) throw new Error("React root did not render the login UI");
    let authenticated = false;
    if (process.env.MAINTAINER_ADMIN_TOKEN_FILE) {
      const token = fs.readFileSync(process.env.MAINTAINER_ADMIN_TOKEN_FILE, "utf8").trim();
      await page.getByLabel("管理员访问令牌").fill(token);
      await page.getByRole("button", { name: /进入控制台/ }).click();
      await page.getByRole("heading", { name: "概览" }).waitFor({ state: "visible", timeout: 10_000 });
      await page.getByRole("button", { name: "GitHub 接入" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "系统设置" }).click();
      await page.getByRole("heading", { name: "系统设置" }).waitFor({ state: "visible" });
      await page.getByText("当前生效配置", { exact: true }).waitFor({ state: "visible" });
      await page.getByText("高级配置", { exact: true }).click();
      await page.getByRole("heading", { name: "Reasoning 覆盖" }).waitFor({ state: "visible" });
      if (await page.getByRole("button", { name: "恢复本组默认" }).count() < 4) throw new Error("Main Agent reset group buttons are incomplete");
      let confirmation = "";
      page.once("dialog", async (dialog) => { confirmation = dialog.message(); await dialog.dismiss(); });
      await page.getByRole("button", { name: "恢复全部默认" }).click();
      if (!confirmation.includes("不会删除 Provider、API Key、模型、Agent、Prompt、GitHub 配置或仓库配置")) throw new Error("Main Agent reset confirmation is not explicit");
      await page.getByRole("button", { name: "模型供应商" }).click();
      await page.getByRole("heading", { name: "模型供应商" }).waitFor({ state: "visible" });
      await page.locator(".model-tag").first().waitFor({ state: "visible" });
      await page.getByRole("button", { name: "编辑", exact: true }).first().click();
      const providerModal = page.locator(".modal").filter({ has: page.getByRole("heading", { name: "编辑供应商" }) });
      await providerModal.getByRole("heading", { name: "编辑供应商" }).waitFor({ state: "visible" });
      await providerModal.locator(".model-editor summary").first().click();
      await providerModal.getByRole("button", { name: "Reasoning · 恢复本组默认" }).first().waitFor({ state: "visible" });
      confirmation = "";
      page.once("dialog", async (dialog) => { confirmation = dialog.message(); await dialog.dismiss(); });
      await providerModal.getByRole("button", { name: "恢复全部默认" }).first().click();
      if (!confirmation.includes("不会删除 Provider、API Key、模型、Agent、Prompt、GitHub 配置或仓库配置")) throw new Error("Model reset confirmation is not explicit");
      await providerModal.getByRole("button", { name: "取消" }).click();
      await providerModal.waitFor({ state: "detached" });
      await page.getByRole("button", { name: "子代理" }).click();
      await page.getByRole("heading", { name: "子代理" }).waitFor({ state: "visible" });
      await page.locator(".runtime-summary").first().waitFor({ state: "visible" });
      const workerCard = page.locator(".agent-cards > section", { hasText: "code_worker" });
      if (await workerCard.count() !== 1) throw new Error(`Expected one code_worker card, found ${await workerCard.count()}`);
      await workerCard.getByRole("button", { name: "编辑代理" }).click();
      await page.waitForTimeout(500);
      if (process.env.MAINTAINER_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.MAINTAINER_SMOKE_SCREENSHOT, fullPage: true });
      if (consoleErrors.length) throw new Error(`Sub Agent dialog crashed: ${JSON.stringify(consoleErrors)}`);
      const agentModal = page.locator(".modal").filter({ has: page.getByRole("heading", { name: "编辑子代理" }) });
      await agentModal.getByRole("heading", { name: "编辑子代理" }).waitFor({ state: "visible" });
      const agentModalText = await agentModal.innerText();
      if (!agentModalText.includes("当前生效配置")) throw new Error(`Sub Agent effective config is missing: ${agentModalText}`);
      await agentModal.getByText("高级覆盖配置", { exact: true }).click();
      if (await agentModal.getByRole("button", { name: "恢复本组默认" }).count() < 4) throw new Error("Sub Agent reset group buttons are incomplete");
      confirmation = "";
      page.once("dialog", async (dialog) => { confirmation = dialog.message(); await dialog.dismiss(); });
      await agentModal.getByRole("button", { name: "恢复全部默认" }).click();
      if (!confirmation.includes("不会删除 Agent、Prompt、Provider、API Key、GitHub 配置或仓库配置")) throw new Error("Sub Agent reset confirmation is not explicit");
      authenticated = true;
    }
    if (consoleErrors.length || failedRequests.length) {
      throw new Error(JSON.stringify({ consoleErrors, failedRequests }));
    }
    console.log(JSON.stringify({ url, status: response.status(), loginVisible: true, authenticated, consoleErrors, failedRequests }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});

