import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const apiBase = "http://127.0.0.1:8875";
const controlledProviderBase = "http://127.0.0.1:8876/v1";
const responsesAccountName = "受控 Responses 写作";
const chatAccountName = "受控 Chat 审核";

async function json(response: Awaited<ReturnType<APIRequestContext["get"]>>) {
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function createBook(request: APIRequestContext, suffix: string) {
  return json(await request.post(`${apiBase}/api/books`, {
    data: {
      draft: {
        title: `浏览器验收-${suffix}-${Date.now()}`,
        platform: "generic",
        styleProfileId: "generic-web-serial",
        styleProfileLabel: "通用网文连载",
        genre: "都市悬疑",
        tagline: "用声音找回被改写的真相。",
        firstChapterTitle: "第一章 试音",
        seed: "主角在雨夜录音里听见自己的警告。"
      },
      existingBookCount: 0,
      defaultModelId: ""
    }
  }));
}

async function installControlledAccounts(request: APIRequestContext) {
  const settings = await json(await request.get(`${apiBase}/api/ai/settings`));
  const ensureAccount = async (name: string, protocol: "responses" | "chat_completions", model: string) => {
    const existing = settings.accounts.find((account: { name: string }) => account.name === name);
    if (existing) {
      const updated = await json(await request.put(
        `${apiBase}/api/ai/accounts/${encodeURIComponent(existing.id)}`,
        {
          data: {
            name,
            purpose: protocol === "responses" ? "玄幻升级与快节奏章节" : "严格审稿与逻辑检查",
            baseUrl: controlledProviderBase,
            apiKey: "e2e-key",
            model,
            protocol,
            maxContextTokens: 128000,
            enabled: true
          }
        }
      ));
      return updated.account.id as string;
    }
    const created = await json(await request.post(`${apiBase}/api/ai/accounts`, {
      data: {
        name,
        purpose: protocol === "responses" ? "玄幻升级与快节奏章节" : "严格审稿与逻辑检查",
        baseUrl: controlledProviderBase,
        apiKey: "e2e-key",
        model,
        protocol,
        maxContextTokens: 128000,
        enabled: true
      }
    }));
    return created.account.id as string;
  };
  const writingAccountId = await ensureAccount(responsesAccountName, "responses", "controlled-responses");
  const reviewAccountId = await ensureAccount(chatAccountName, "chat_completions", "controlled-chat");
  await json(await request.put(`${apiBase}/api/ai/roles`, {
    data: { writingAccountId, reviewAccountId }
  }));
  return { writingAccountId, reviewAccountId };
}

async function removeControlledAccounts(request: APIRequestContext) {
  const settings = await json(await request.get(`${apiBase}/api/ai/settings`));
  for (const account of settings.accounts as Array<{ id: string; name: string }>) {
    if ([responsesAccountName, chatAccountName].includes(account.name)) {
      await json(await request.delete(`${apiBase}/api/ai/accounts/${encodeURIComponent(account.id)}`));
    }
  }
}

async function prepareConfirmedBlueprint(request: APIRequestContext, bookId: string, prefix: string) {
  const generationPath = `${apiBase}/api/books/${encodeURIComponent(bookId)}/generation`;
  const directions = await json(await request.post(`${generationPath}/continue`, {
    data: { bookId, requestId: `${prefix}-directions-${Date.now()}` }
  }));
  await json(await request.post(`${generationPath}/confirm`, {
    data: { bookId, optionId: directions.generationState.candidateOptions[0].id }
  }));
  await json(await request.post(`${generationPath}/continue`, {
    data: { bookId, requestId: `${prefix}-long-form-${Date.now()}` }
  }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));
  await json(await request.post(`${generationPath}/continue`, {
    data: { bookId, requestId: `${prefix}-blueprint-${Date.now()}` }
  }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));
}

async function openBook(page: Page, title: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "打开书架切换作品" }).click();
  await page.getByPlaceholder("搜索书名、题材或下一步").fill(title);
  await page.locator(".ant-card").filter({ hasText: title }).getByRole("button", { name: "打开" }).click();
}

async function restartBackend() {
  const generationPath = resolve(".e2e-runtime/backend-generation");
  const restartPath = resolve(".e2e-runtime/restart-backend");
  const previousGeneration = Number(await readFile(generationPath, "utf8"));
  await writeFile(restartPath, "restart\n", "utf8");
  await expect.poll(
    async () => Number(await readFile(generationPath, "utf8")),
    { timeout: 15_000 }
  ).toBe(previousGeneration + 1);
  await expect.poll(async () => {
    try {
      return (await fetch(`${apiBase}/health`)).ok;
    } catch {
      return false;
    }
  }, { timeout: 15_000 }).toBeTruthy();
}

test("sidebar runs automatic detection and mode-aware one-click update after reconnect", async ({ page, request }) => {
  const created = await createBook(request, "online-update");
  let installed = false;
  let statusChecksAfterInstall = 0;
  await page.route("**/api/system/update", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        checkSucceeded: true,
        currentVersion: installed ? "0.2.0" : "0.1.0",
        latestVersion: "0.2.0",
        updateAvailable: !installed,
        downloadReady: true,
        status: installed ? "已是最新版本" : "发现新版本",
        message: installed ? "当前版本 0.2.0 已是最新版本。" : "版本 0.2.0 已发布，可以下载安装。",
        releaseName: "Open Novel 0.2.0",
        releaseNotes: "",
        publishedAt: "",
        releaseUrl: "",
        packageUrl: "https://example.test/open-novel-0.2.0.zip",
        checksumUrl: "https://example.test/open-novel-0.2.0.zip.sha256",
        deploymentMode: "compose",
        deploymentLabel: "Docker Compose",
        automaticUpdateReady: true,
        automaticUpdateMessage: "宿主机更新助手已连接。"
      })
    });
  });
  await page.route("**/api/system/update/auto-detect", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        checkSucceeded: true,
        currentVersion: installed ? "0.2.0" : "0.1.0",
        latestVersion: "0.2.0",
        updateAvailable: !installed,
        downloadReady: true,
        status: installed ? "已是最新版本" : "发现新版本",
        message: installed ? "当前版本 0.2.0 已是最新版本。" : "版本 0.2.0 已发布，可以下载安装。",
        releaseName: "Open Novel 0.2.0",
        releaseNotes: "",
        publishedAt: "",
        releaseUrl: "",
        packageUrl: "https://example.test/open-novel-0.2.0.zip",
        checksumUrl: "https://example.test/open-novel-0.2.0.zip.sha256",
        deploymentMode: "compose",
        deploymentLabel: "Docker Compose",
        automaticUpdateReady: true,
        automaticUpdateMessage: "宿主机更新助手已连接。",
        checkedAt: new Date().toISOString(),
        pollIntervalSeconds: 60
      })
    });
  });
  await page.route("**/api/system/update/status", async (route) => {
    if (!installed) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          phase: "idle",
          status: "尚未开始更新",
          message: "可以先检查是否有新版本。",
          currentVersion: "0.1.0",
          targetVersion: "",
          deploymentMode: "compose",
          finished: true,
          succeeded: false,
          rolledBack: false,
          updatedAt: ""
        })
      });
      return;
    }
    statusChecksAfterInstall += 1;
    if (statusChecksAfterInstall === 1) {
      await route.abort("connectionrefused");
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        phase: "success",
        status: "更新成功",
        message: "Docker Compose 已更新到版本 0.2.0。",
        currentVersion: "0.1.0",
        targetVersion: "0.2.0",
        deploymentMode: "compose",
        finished: true,
        succeeded: true,
        rolledBack: false,
        updatedAt: new Date().toISOString()
      })
    });
  });
  await page.route("**/api/system/update/install", async (route) => {
    installed = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "自动更新已启动",
        message: "宿主机更新助手已接收请求，服务将自动重启。",
        currentVersion: "0.1.0",
        targetVersion: "0.2.0",
        planPath: "/app/.open-novel/updates/0.2.0/update-plan.json",
        packagePath: "/app/.open-novel/updates/0.2.0/open-novel-0.2.0.zip",
        databaseBackupPath: "/app/.open-novel/updates/0.2.0/workspace-before-update.sqlite3",
        restartRequired: true,
        deploymentMode: "compose",
        shutdownRequired: false
      })
    });
  });

  await openBook(page, created.book.title);
  await page.getByRole("button", { name: "当前版本 v0.1.0" }).click();
  await expect(page.getByText("发现新版本 v0.2.0", { exact: true })).toBeVisible();
  await expect(page.getByText("Docker Compose · 每分钟自动检查", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "一键更新" }).click();
  await expect(page.getByText("等待服务恢复")).toBeVisible({ timeout: 5_000 });
  await expect(page.getByText("更新成功", { exact: true })).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole("button", { name: "当前版本 v0.2.0" })).toBeVisible();
});

test("AI model menu configures roles, both API channels, probes and token usage", async ({ page, request }) => {
  test.setTimeout(90_000);
  await removeControlledAccounts(request);
  await page.goto("/");
  await page.locator(".sidebar-link").filter({ hasText: "AI 模型" }).click();
  await expect(page.getByText("模型方案与 AI 账号统一管理")).toBeVisible();
  await page.getByRole("tab", { name: "AI 账号" }).click();
  await expect(page.getByText("连接账号集中放在这里")).toBeVisible();

  const addAccount = async (
    name: string,
    protocolLabel: "Responses API" | "Chat Completions API",
    model: string
  ) => {
    await page.getByRole("button", { name: "新增账号" }).click();
    const dialog = page.getByRole("dialog", { name: "新增 AI 账号" });
    await dialog.getByLabel("账号名称").fill(name);
    await dialog.getByLabel("适合内容").fill(name === responsesAccountName ? "玄幻升级与快节奏章节" : "严格审稿与逻辑检查");
    await dialog.locator(".ant-select-selector").first().click();
    await page.getByText(protocolLabel, { exact: true }).last().click();
    await dialog.getByLabel("Base URL").fill(controlledProviderBase);
    await dialog.getByLabel("API Key").fill("e2e-key");
    const modelsResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/ai/models/discover") && response.request().method() === "POST"
    );
    await dialog.getByRole("button", { name: "自动获取模型" }).click();
    expect((await modelsResponsePromise).ok()).toBeTruthy();
    const modelDropdown = page.locator(".ant-select-dropdown:visible");
    await expect(modelDropdown.getByText("controlled-responses", { exact: true }).last()).toBeVisible();
    await expect(modelDropdown.getByText("controlled-chat", { exact: true }).last()).toBeVisible();
    await dialog.locator('input[role="combobox"]').last().fill(model);
    await dialog.getByRole("spinbutton", { name: "最大上下文" }).fill("128");
    const formProbePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/ai/probe") && response.request().method() === "POST"
    );
    await dialog.getByRole("button", { name: "拨测当前配置（发送 hi）" }).click();
    expect((await formProbePromise).ok()).toBeTruthy();
    await expect(dialog.getByText("拨测通过")).toBeVisible();
    await dialog.getByRole("button", { name: "保存账号" }).click();
    await expect(dialog).toBeHidden();
  };

  await addAccount(responsesAccountName, "Responses API", "controlled-responses");
  await addAccount(chatAccountName, "Chat Completions API", "controlled-chat");

  await page.getByRole("tab", { name: "模型方案" }).click();
  await expect(page.getByText("按文风选择")).toBeVisible();
  const rolePanels = page.locator(".ai-role-grid > div");
  await rolePanels.nth(0).locator(".ant-select-selector").click();
  await page.getByText(`${responsesAccountName} · controlled-responses`, { exact: true }).last().click();
  await rolePanels.nth(1).locator(".ant-select-selector").click();
  await page.getByText(`${chatAccountName} · controlled-chat`, { exact: true }).last().click();
  const roleResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/ai/roles") && response.request().method() === "PUT"
  );
  await page.getByRole("button", { name: "保存角色" }).click();
  const roleResponse = await roleResponsePromise;
  expect(roleResponse.ok(), await roleResponse.text()).toBeTruthy();
  await expect(page.getByText("角色分配已保存并立即生效。")).toBeVisible();

  await page.getByRole("tab", { name: "AI 账号" }).click();
  const responsesRow = page.locator(".ant-table-row").filter({ hasText: responsesAccountName });
  const chatRow = page.locator(".ant-table-row").filter({ hasText: chatAccountName });
  const responsesProbePromise = page.waitForResponse(
    (response) => response.url().endsWith("/probe") && response.request().method() === "POST"
  );
  await responsesRow.getByRole("button", { name: "拨测" }).click();
  const responsesProbe = await responsesProbePromise;
  expect(responsesProbe.ok(), await responsesProbe.text()).toBeTruthy();
  const chatProbePromise = page.waitForResponse(
    (response) => response.url().endsWith("/probe") && response.request().method() === "POST"
  );
  await chatRow.getByRole("button", { name: "拨测" }).click();
  const chatProbe = await chatProbePromise;
  expect(chatProbe.ok(), await chatProbe.text()).toBeTruthy();
  await expect(page.getByRole("heading", { name: "Token 使用量" })).toBeVisible();
  await expect(page.locator(".ant-table-row").filter({ hasText: "账号拨测" })).toHaveCount(4);

  const settings = await json(await request.get(`${apiBase}/api/ai/settings`));
  const writingAccount = settings.accounts.find((account: { name: string }) => account.name === responsesAccountName);
  const reviewAccount = settings.accounts.find((account: { name: string }) => account.name === chatAccountName);
  expect(writingAccount.protocol).toBe("responses");
  expect(reviewAccount.protocol).toBe("chat_completions");
  expect(settings.roles).toEqual({
    writingAccountId: writingAccount.id,
    reviewAccountId: reviewAccount.id
  });
  const probeEvents = settings.usageEvents.filter(
    (event: { action: string; accountId: string }) =>
      event.action === "账号拨测" && [writingAccount.id, reviewAccount.id].includes(event.accountId)
  );
  expect(probeEvents).toHaveLength(2);
  expect(probeEvents.every((event: { totalTokens: number }) => event.totalTokens > 0)).toBeTruthy();

  await page.locator(".sidebar-link").filter({ hasText: "我的模型" }).click();
  await expect(page.getByRole("main").getByRole("heading", { name: "我的模型" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "内置模板" })).toBeVisible();
  await expect(page.getByText("14 种", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "使用 东方玄幻升级流 模板" }).click();
  const templateDialog = page.getByRole("dialog", { name: "新增模型" });
  await expect(templateDialog.getByLabel("模型名称")).toHaveValue("东方玄幻升级流");
  await expect(templateDialog.getByText("模仿节奏", { exact: true })).toBeVisible();
  await expect(templateDialog.getByLabel("说明")).toHaveValue(
    "强化升级反馈、阶段目标、冲突递进和章末钩子。"
  );
  await templateDialog.getByRole("button", { name: "Close" }).click();
  await expect(templateDialog).toBeHidden();
  const modelName = `端到端公共模型-${Date.now()}`;
  const categoryName = `端到端分类-${Date.now()}`;
  await page.getByRole("button", { name: "新增模型" }).first().click();
  await page.getByLabel("模型名称").fill(modelName);
  await page.getByRole("button", { name: "新增分类" }).click();
  await page.getByPlaceholder("输入分类名称").fill(categoryName);
  await page.getByRole("button", { name: "创建分类" }).click();
  await expect(page.getByText(categoryName)).toBeVisible();
  await page.getByRole("button", { name: "创建模型" }).click();
  await expect(page.getByText(modelName).first()).toBeVisible();

  await page.getByRole("button", { name: "上传文章" }).click();
  await page.locator('input[type="file"]').setInputFiles([
    {
      name: "训练样本.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("这是合格训练素材。".repeat(100))
    },
    {
      name: "过短样本.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("内容太短。")
    }
  ]);
  await page.getByRole("button", { name: "添加文章" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("已添加 1 个")).toBeVisible();
  await expect(page.getByText("未通过 1 个")).toBeVisible();
  await expect(page.getByText("正文少于 500 字").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "训练样本.txt" })).toBeVisible();
  await expect(page.getByText("可训练").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "训练版本" })).toBeVisible();
  await expect(page.getByText("训练完成后会在这里生成版本。")).toBeVisible();
  await expect(page.getByText("自动选择")).toBeVisible();
  await expect(page.getByText("MLX-LM")).toBeVisible();
  await expect(page.getByText("LLaMA Factory")).toBeVisible();
  await expect(
    page.getByRole("alert").getByRole("button", { name: "继续添加" })
  ).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  const modelScreenshotDir = resolve("output/playwright");
  await mkdir(modelScreenshotDir, { recursive: true });
  await page.locator(".model-library-page").screenshot({
    path: resolve(modelScreenshotDir, "model-library-detail-desktop.png")
  });
});

test("unfinished chapters block next chapter and library keeps one create entry", async ({ page }) => {
  await page.goto("/");
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  await expect(page.getByRole("button", { name: "开始下一章" })).toBeDisabled();
  await expect(page.getByText(/当前章正式完稿并接收后|请先回到最新章节/)).toBeVisible();
  const editor = page.locator(".chapter-editor");
  const originalDraft = await editor.inputValue();
  const localDraft = `${originalDraft}\n\n这是尚未保存的跨页面草稿。`;
  await editor.fill(localDraft);
  await page.locator(".sidebar-link").filter({ hasText: "AI 模型" }).click();
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  await expect(page.locator(".chapter-editor")).toHaveValue(localDraft);
  await page.locator(".chapter-editor").fill(originalDraft);

  await page.locator(".sidebar-link").filter({ hasText: "资料" }).click();
  const createMaterial = page.getByRole("button", { name: "新增人物" });
  await expect(createMaterial).toHaveCount(1);
  await createMaterial.click();
  await expect(page.getByRole("heading", { name: "新增人物" })).toBeVisible();
});

test("new book opens a guided direction candidate and keeps settings editable", async ({ page, request }) => {
  test.setTimeout(150_000);
  await installControlledAccounts(request);
  const title = `页面连续创建-${Date.now()}`;
  await page.goto("/");
  await page.getByRole("button", { name: "打开书架切换作品" }).click();
  await page.getByRole("button", { name: "新建作品" }).first().click();
  const dialog = page.getByRole("dialog", { name: "新建作品" });
  const styleSelect = dialog.locator(".ant-select").first();
  await expect(styleSelect).not.toHaveClass(/ant-select-disabled/);
  await styleSelect.locator(".ant-select-selector").click();
  const styleOptions = page.locator(".new-book-style-popup .style-option-title");
  await expect(styleOptions.first()).toBeVisible();
  const styleLabels = await styleOptions.allTextContents();
  expect(styleLabels.length).toBeGreaterThan(0);
  expect(styleLabels.every((label) => /[\u4e00-\u9fff]/.test(label) && !/[A-Za-z]/.test(label))).toBeTruthy();
  await page.keyboard.press("Escape");
  await dialog.getByPlaceholder("作品名称").fill(title);
  await dialog.getByPlaceholder("一句话简介").fill("创建后仍可继续修改作品设置。");
  await dialog.getByPlaceholder("首章标题").fill("第一章 雨声");
  await dialog.getByPlaceholder(/给 AI 的新书想法/).fill("雨夜录音预告了主角明天的选择。");
  await dialog.getByRole("button", { name: "下一步" }).click();
  await expect(dialog.getByText("生成将使用“AI 模型”中的写作角色")).toBeVisible();
  await dialog.getByRole("button", { name: "上一步" }).click();
  await expect(dialog.getByPlaceholder("作品名称")).toHaveValue(title);
  await dialog.getByRole("button", { name: "下一步" }).click();
  for (const label of ["自动推进", "阶段确认", "逐章确认", "深度参与"]) {
    await dialog.getByText(label, { exact: true }).click();
    await expect(dialog.getByRole("alert").last()).toBeVisible();
  }
  await dialog.getByText("阶段确认", { exact: true }).click();
  await dialog.getByRole("spinbutton", { name: "全书目标章节数" }).fill("160");
  await dialog.getByRole("spinbutton", { name: "每章目标字数" }).fill("3300");
  await dialog.getByRole("spinbutton", { name: "每个剧情段目标章节数" }).fill("12");
  await dialog.getByRole("button", { name: "下一步" }).click();
  await expect(dialog.getByText(/创建后立即进入生成主控台/)).toBeVisible();
  await expect(dialog.getByRole("heading", { name: title })).toBeVisible();
  const createResponsePromise = page.waitForResponse((response) =>
    response.url() === `${apiBase}/api/books` && response.request().method() === "POST"
  );
  await dialog.getByRole("button", { name: "创建并生成方向" }).click();
  const createResponse = await createResponsePromise;
  expect(createResponse.ok(), await createResponse.text()).toBeTruthy();
  const created = await createResponse.json();
  expect(createResponse.request().postDataJSON()).toMatchObject({
    targetChapterCount: 160,
    targetWordsPerChapter: 3300,
    targetChaptersPerPlot: 12
  });
  expect(created.book.title).toBe(title);
  expect(created.generationState.activeArtifactType).toBe("book_direction");

  await expect(page.getByRole("heading", { name: /作品方向 · 版本/ })).toBeVisible();
  await expect(page.getByText(title).first()).toBeVisible();
  await expect(page.getByText("当前只需处理：作品架构")).toBeVisible();
  const generationPage = page.locator(".generation-page");
  await expect(generationPage).toHaveCSS("overflow-y", "visible");
  const generationBounds = await generationPage.evaluate((node) => {
    return {
      clientHeight: node.clientHeight,
      scrollHeight: node.scrollHeight
    };
  });
  expect(generationBounds.scrollHeight).toBeLessThanOrEqual(generationBounds.clientHeight + 1);
  const pipelineCard = page.locator(".generation-scroll-card").filter({ hasText: "生成流水线" });
  await expect(pipelineCard.locator(".ant-card-body").first()).toHaveCSS("overflow-y", "visible");
  await expect(pipelineCard.getByText("未开始")).toHaveCount(9);
  await expect(page.getByRole("spinbutton", { name: "全书目标章节数" })).toHaveValue("160");
  await expect(page.getByRole("spinbutton", { name: "每章目标字数" })).toHaveValue("3300");
  await expect(page.getByRole("spinbutton", { name: "每个剧情段目标章节数" })).toHaveValue("12");
  await page.getByRole("spinbutton", { name: "每章目标字数" }).fill("3500");
  const planResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/plan") && response.request().method() === "PUT"
  );
  await page.getByRole("button", { name: "保存作品参数" }).click();
  const planResponse = await planResponsePromise;
  expect(planResponse.ok(), await planResponse.text()).toBeTruthy();
  expect((await planResponse.json()).plan.targetWordsPerChapter).toBe(3500);

  await page.getByRole("button", { name: "打开书架切换作品" }).click();
  await page.getByRole("button", { name: "编辑设置" }).click();
  const settingsDialog = page.getByRole("dialog", { name: "编辑作品设置" });
  await settingsDialog.locator("input").first().fill(`${title}-修订`);
  await settingsDialog.locator("textarea").fill("作品简介已允许在创建后继续修改。");
  const settingsResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/settings") && response.request().method() === "PUT"
  );
  await settingsDialog.getByRole("button", { name: "保存设置" }).click();
  const settingsResponse = await settingsResponsePromise;
  expect(settingsResponse.ok(), await settingsResponse.text()).toBeTruthy();
  await expect(page.getByRole("heading", { name: `${title}-修订` }).first()).toBeVisible();
  await expect(page.getByText("作品简介已允许在创建后继续修改。").first()).toBeVisible();
});

test("stage confirmation lets authors review all five candidate types", async ({ page, request }) => {
  test.setTimeout(90_000);
  const screenshotDir = resolve("output/playwright/state-audit/generation-candidates");
  await mkdir(screenshotDir, { recursive: true });
  const created = await createBook(request, "stage-confirm");
  const bookId = created.book.id;
  const path = `${apiBase}/api/books/${encodeURIComponent(bookId)}/generation`;
  await installControlledAccounts(request);
  const openCreatedBook = async () => {
    await page.goto("/");
    await page.getByRole("button", { name: "打开书架切换作品" }).click();
    await page.getByPlaceholder("搜索书名、题材或下一步").fill(created.book.title);
    await page.locator(".ant-card").filter({ hasText: created.book.title }).getByRole("button", { name: "打开" }).click();
  };
  const captureCandidate = async (slug: string) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.screenshot({
      path: resolve(screenshotDir, `${slug}-desktop.png`),
      fullPage: true
    });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
    await page.screenshot({
      path: resolve(screenshotDir, `${slug}-mobile.png`),
      fullPage: true
    });
    await page.setViewportSize({ width: 1280, height: 720 });
  };

  const directions = await json(await request.post(`${path}/continue`, { data: { bookId, requestId: `directions-${Date.now()}` } }));
  expect(directions.generationState.activeArtifactType).toBe("book_direction");
  expect(directions.generationState.candidateOptions).toHaveLength(3);
  await openCreatedBook();
  await expect(page.getByRole("heading", { name: /作品方向 · 版本/ })).toBeVisible();
  await captureCandidate("book-direction");
  const architecture = await json(await request.post(`${path}/confirm`, {
    data: { bookId, optionId: directions.generationState.candidateOptions[1].id, requestId: `confirm-direction-${Date.now()}` }
  }));
  expect(architecture.generationState.stage).toBe("blueprint");

  const longForm = await json(await request.post(`${path}/continue`, { data: { bookId, requestId: `long-form-${Date.now()}` } }));
  expect(longForm.generationState.activeArtifactType).toBe("long_form_plan");
  await openCreatedBook();
  await expect(page.getByRole("heading", { name: /长篇规划 · 版本/ })).toBeVisible();
  await captureCandidate("long-form-plan");
  await json(await request.post(`${path}/confirm`, { data: { bookId, requestId: `confirm-long-form-${Date.now()}` } }));
  const blueprint = await json(await request.post(`${path}/continue`, { data: { bookId, requestId: `blueprint-${Date.now()}` } }));
  expect(blueprint.generationState.activeArtifactType).toBe("chapter_blueprint");
  await openCreatedBook();
  await expect(page.getByRole("heading", { name: /章节蓝图 · 版本/ })).toBeVisible();
  await captureCandidate("chapter-blueprint");
  const blueprintExpand = page.getByRole("button", { name: /查看全部 \d+ 项/ });
  if (await blueprintExpand.count()) {
    await blueprintExpand.click();
    await expect(page.getByRole("button", { name: "收起详情" })).toBeVisible();
    await page.getByRole("button", { name: "收起详情" }).click();
  }
  await json(await request.post(`${path}/confirm`, { data: { bookId, requestId: `confirm-blueprint-${Date.now()}` } }));
  await json(await request.put(`${path}/mode`, {
    data: { bookId, interventionMode: "deep_control", batchTarget: 1 }
  }));
  const contract = await json(await request.post(`${path}/continue`, { data: { bookId, requestId: `contract-${Date.now()}` } }));
  expect(contract.generationState.activeArtifactType).toBe("scene_contract");
  await openCreatedBook();
  await expect(page.getByRole("heading", { name: /章节规划 · 版本/ })).toBeVisible();
  await captureCandidate("scene-contract");
  const contractExpand = page.getByRole("button", { name: /查看全部 \d+ 项/ });
  if (await contractExpand.count()) {
    await contractExpand.click();
    await expect(page.getByRole("button", { name: "收起详情" })).toBeVisible();
    await page.getByRole("button", { name: "收起详情" }).click();
  }
  const confirmedContract = await json(await request.post(`${path}/confirm`, {
    data: { bookId, requestId: `confirm-contract-${Date.now()}` }
  }));
  expect(confirmedContract.generationState.stage).toBe("context");
  let draft = await json(await request.post(`${path}/continue`, { data: { bookId, requestId: `draft-${Date.now()}-1` } }));
  if (draft.generationState.activeArtifactType !== "chapter_draft") {
    draft = await json(await request.post(`${path}/continue`, { data: { bookId, requestId: `draft-${Date.now()}-2` } }));
  }
  expect(draft.generationState.activeArtifactType).toBe("chapter_draft");
  await openCreatedBook();
  await expect(page.getByRole("heading", { name: /章节正文 · 版本/ })).toBeVisible();
  await captureCandidate("chapter-draft");
  await page.getByRole("button", { name: "展开完整正文" }).click();
  await expect(page.getByRole("button", { name: "收起正文" })).toBeVisible();
  await page.getByRole("button", { name: "收起正文" }).click();
});

test("author edits a volume goal, compares replan and inspects changed landing", async ({ page, request }) => {
  test.setTimeout(90_000);
  const created = await createBook(request, "long-form-console");
  const bookId = created.book.id;
  const generationPath = `${apiBase}/api/books/${encodeURIComponent(bookId)}/generation`;
  await installControlledAccounts(request);
  const directions = await json(await request.post(`${generationPath}/continue`, {
    data: { bookId, requestId: `console-directions-${Date.now()}` }
  }));
  await json(await request.post(`${generationPath}/confirm`, {
    data: { bookId, optionId: directions.generationState.candidateOptions[0].id }
  }));
  await json(await request.post(`${generationPath}/continue`, {
    data: { bookId, requestId: `console-plan-${Date.now()}` }
  }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));
  await json(await request.post(`${generationPath}/continue`, {
    data: { bookId, requestId: `console-blueprint-${Date.now()}` }
  }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));

  await page.goto("/");
  await page.getByRole("button", { name: "打开书架切换作品" }).click();
  await page.getByPlaceholder("搜索书名、题材或下一步").fill(created.book.title);
  await page.locator(".ant-card").filter({ hasText: created.book.title }).getByRole("button", { name: "打开" }).click();
  await page.getByRole("button", { name: "资料" }).click();
  const materialTypeTabs = page.getByRole("tablist", { name: "资料类型" });
  await expect(materialTypeTabs.getByRole("tab")).toHaveCount(8);
  await expect(materialTypeTabs).toHaveCSS("overflow-x", "visible");
  await expect(materialTypeTabs).toHaveCSS("flex-wrap", "wrap");
  const librarySide = page.locator(".library-side-column");
  await expect(librarySide).toHaveCSS("position", "sticky");
  await expect(librarySide).toHaveCSS("overflow-y", "visible");
  await expect(page.locator(".library-workbench-fixed")).toContainText("资料工作台");
  await expect(page.locator(".library-memory-scroll")).not.toContainText("资料工作台");
  await expect(page.locator(".library-workbench-fixed")).toHaveCSS("overflow-y", "visible");
  const librarySideBounds = await librarySide.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return { right: rect.right, viewportWidth: window.innerWidth };
  });
  expect(librarySideBounds.right).toBeLessThanOrEqual(librarySideBounds.viewportWidth + 1);
  await page.getByRole("tab", { name: "当前卷" }).click();
  await page.getByLabel("卷目标").fill("让居民共同决定城市规则");
  await page.getByRole("button", { name: "保存卷目标与边界" }).click();
  await expect(page.getByText("卷目标已保存，后续重规划只影响未定稿章节。")).toBeVisible();
  await page.getByRole("button", { name: "生成重规划候选" }).click();
  await page.getByRole("button", { name: "比较重规划" }).click();
  await expect(page.getByRole("tab", { name: "重规划比较", selected: true })).toBeVisible();
  await expect(page.getByText(/当前：让居民共同决定城市规则/).first()).toBeVisible();
  await page.getByRole("button", { name: "确认重规划" }).click();
  await expect(page.getByText("重规划候选已确认。")).toBeVisible();
  await page.getByRole("tab", { name: "章节落点" }).click();
  await expect(page.getByText(/目标：重规划目标 1/).first()).toBeVisible();
  await expect(page.getByText(/依赖：承接第 1 章/).first()).toBeVisible();
});

test("author compares direction and blueprint versions, selects older work and returns to the previous confirmation", async ({ page, request }) => {
  test.setTimeout(90_000);
  const title = `浏览器候选决策-${Date.now()}`;
  const created = await json(await request.post(`${apiBase}/api/books`, {
    data: {
      draft: {
        title,
        platform: "generic",
        styleProfileId: "generic-web-serial",
        styleProfileLabel: "通用网文连载",
        genre: "都市悬疑",
        tagline: "候选版本必须能够比较和返回。",
        firstChapterTitle: "第一章 试音",
        seed: "雨夜录音出现未来警告。"
      },
      existingBookCount: 0,
      defaultModelId: ""
    }
  }));
  await installControlledAccounts(request);
  const workspace = await json(await request.get(`${apiBase}/api/workspace`));
  expect(workspace.books.some((book: { id: string }) => book.id === created.book.id)).toBeTruthy();

  await page.goto("/");
  await expect(page.getByText(title).first()).toBeVisible();
  await page.getByRole("button", { name: "生成作品架构" }).click();
  const candidateHeading = page.getByRole("heading", { name: /作品方向 · 版本/ });
  await expect(candidateHeading).toBeVisible();
  const firstVersion = Number((await candidateHeading.textContent())?.match(/版本 (\d+)/)?.[1] ?? "0");
  expect(firstVersion).toBeGreaterThan(0);

  await page.getByRole("button", { name: "重新生成" }).click();
  const regenerateDialog = page.getByRole("dialog", { name: "重新生成当前阶段候选？" });
  await regenerateDialog.getByRole("button", { name: "重新生成" }).click();
  await expect(candidateHeading).toHaveText(`作品方向 · 版本 ${firstVersion + 1}`);
  await expect(regenerateDialog).toBeHidden();
  await page.getByRole("button", { name: "重新生成" }).click();
  await regenerateDialog.getByRole("button", { name: "重新生成" }).click();
  await expect(candidateHeading).toHaveText(`作品方向 · 版本 ${firstVersion + 2}`);
  await expect(regenerateDialog).toBeHidden();
  await expect(page.getByLabel("候选版本", { exact: true }).locator("option")).toHaveCount(firstVersion + 2);
  await page.getByRole("button", { name: "比较版本" }).click();
  const compareDialog = page.getByRole("dialog", { name: "候选版本比较" });
  await expect(compareDialog).toBeVisible();
  await compareDialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(compareDialog).toBeHidden();

  const candidateVersionSelect = page.getByLabel("候选版本", { exact: true });
  const olderCandidateId = await candidateVersionSelect.locator("option").nth(1).getAttribute("value");
  expect(olderCandidateId).toBeTruthy();
  await candidateVersionSelect.selectOption(olderCandidateId!);
  await expect(candidateHeading).not.toHaveText(`作品方向 · 版本 ${firstVersion + 2}`);
  const selectedVersion = Number((await candidateHeading.textContent())?.match(/版本 (\d+)/)?.[1] ?? "0");
  expect(selectedVersion).toBeGreaterThan(0);
  await page.getByRole("button", { name: "确认并继续" }).click();
  await page.getByRole("button", { name: "生成章节蓝图" }).click();
  await expect(page.getByRole("heading", { name: /长篇规划 · 版本/ })).toBeVisible();
  await page.getByRole("button", { name: "确认并继续" }).click();
  await page.getByRole("button", { name: "生成章节蓝图" }).click();
  const blueprintHeading = page.getByRole("heading", { name: /章节蓝图 · 版本/ });
  await expect(blueprintHeading).toBeVisible();
  const firstBlueprintVersion = Number((await blueprintHeading.textContent())?.match(/版本 (\d+)/)?.[1] ?? "0");
  const initialBlueprintId = await page.getByLabel("候选版本", { exact: true }).inputValue();
  await page.getByRole("button", { name: "重新生成" }).click();
  await page.getByRole("dialog", { name: "重新生成当前阶段候选？" }).getByRole("button", { name: "重新生成" }).click();
  await expect(blueprintHeading).toHaveText(`章节蓝图 · 版本 ${firstBlueprintVersion + 1}`);
  await page.getByRole("button", { name: "比较版本" }).click();
  await expect(page.getByRole("dialog", { name: "候选版本比较" })).toBeVisible();
  await page.getByRole("dialog", { name: "候选版本比较" }).getByRole("button", { name: "Close", exact: true }).click();
  const blueprintVersionSelect = page.getByLabel("候选版本", { exact: true });
  await blueprintVersionSelect.selectOption(initialBlueprintId);
  await expect(blueprintHeading).toHaveText(`章节蓝图 · 版本 ${firstBlueprintVersion}`);
  await page.getByRole("button", { name: "返回上一确认点" }).click();
  await page.getByRole("dialog", { name: "返回上一个确认点？" }).getByRole("button", { name: "确认返回" }).click();
  await expect(page.getByRole("heading", { name: /长篇规划 · 版本/ })).toBeVisible();
});

test("deep control edits the scene contract, generates a draft and accepts it after gate", async ({ page, request }) => {
  test.setTimeout(120_000);
  const created = await createBook(request, "deep-control");
  const bookId = created.book.id;
  await installControlledAccounts(request);
  await prepareConfirmedBlueprint(request, bookId, "deep-control");
  await openBook(page, created.book.title);

  await page.getByText("深度干预", { exact: true }).click();
  const modeResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/generation/mode") && response.request().method() === "PUT"
  );
  await page.getByRole("button", { name: "保存设置" }).click();
  expect((await modeResponsePromise).ok()).toBeTruthy();
  await page.locator(".hero-panel").getByRole("button", { name: "继续生成" }).click();
  await expect(page.getByRole("heading", { name: /章节规划 · 版本/ })).toBeVisible();
  await page.getByRole("button", { name: "确认并继续" }).click();

  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  const chapterSideTabs = page.getByRole("tablist", { name: "章节辅助面板" });
  await expect(chapterSideTabs.getByRole("tab")).toHaveCount(9);
  await expect(chapterSideTabs).toHaveCSS("overflow-x", "visible");
  await expect(chapterSideTabs).toHaveCSS("flex-wrap", "wrap");
  for (const label of ["任务", "资料", "人物", "线索", "审阅", "经验", "创意", "上下文", "场景"]) {
    await expect(chapterSideTabs.getByRole("tab", { name: label })).toBeVisible();
  }
  const chapterAssist = page.getByLabel("章节辅助内容");
  await expect(chapterAssist).toHaveCSS("overflow-y", "visible");
  await expect(page.locator(".writing-page-grid > .main-column")).toHaveCSS("overflow-y", "visible");
  await expect(page.locator(".writing-toolbar")).toHaveCSS("position", "sticky");
  const assistText = await chapterAssist.textContent();
  expect(assistText).not.toContain("剧情方向");
  expect(assistText).not.toContain("AI 写作助手");
  const aiWorkbench = page.locator(".writing-candidate-pane .writing-ai-workbench");
  await expect(aiWorkbench).toContainText("AI 工作区");
  await expect(aiWorkbench.getByRole("button", { name: "AI 续写" })).toBeVisible();
  await expect(page.locator(".writing-side-column")).not.toContainText("AI 工作区");
  await chapterSideTabs.getByRole("tab", { name: "创意" }).click();
  await expect(chapterAssist.getByText("剧情方向", { exact: true })).toBeVisible();
  await expect(chapterAssist.getByText("创意会话", { exact: true })).toBeVisible();
  await chapterSideTabs.getByRole("tab", { name: "场景" }).click();
  await page.getByLabel("开场钩子", { exact: true }).fill("广告灯第四次熄灭时，原始录音突然播出主角的声音");
  await page.getByLabel("余味", { exact: true }).fill("证据被保住，但废弃机房的倒计时已经开始");
  const contractResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/contract") && response.request().method() === "PUT"
  );
  await page.getByRole("button", { name: "保存章节规划" }).click();
  expect((await contractResponsePromise).ok()).toBeTruthy();

  await page.getByRole("button", { name: "AI 续写" }).click();
  await expect(page.getByText("修改意见", { exact: true })).toBeVisible();
  await page.getByPlaceholder("例如：冲突提前，减少解释，保留结尾钩子").fill("把冲突提前，并保留原始录音证据。");
  const revisionRequestPromise = page.waitForRequest(
    (request) => request.url().endsWith("/api/agent/assist/stream") && request.method() === "POST"
  );
  await page.getByRole("button", { name: "按修改意见重新生成" }).click();
  const revisionRequest = await revisionRequestPromise;
  expect(revisionRequest.postDataJSON()).toMatchObject({ bypassCache: true });
  expect(revisionRequest.postDataJSON().input).toContain("把冲突提前，并保留原始录音证据。");

  await page.locator(".sidebar-link").filter({ hasText: "生成" }).click();
  await page.locator(".hero-panel").getByRole("button", { name: "继续生成" }).click();
  await expect(page.getByRole("heading", { name: /章节正文 · 版本/ })).toBeVisible();
  await page.getByRole("button", { name: "确认并继续" }).click();
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  await expect(page.locator(".chapter-editor")).toContainText("异常声纹");
  const [gateResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate") && response.request().method() === "POST"),
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate/recovery") && response.request().method() === "GET"),
    page.getByRole("button", { name: "接收前检查" }).click()
  ]);
  expect((await gateResponse.json()).gate.status).not.toBe("block");
  const acceptResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/accept") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "确认接收" }).click();
  const accepted = await (await acceptResponsePromise).json();
  expect(accepted.chapter.status).toBe("完成");
});

test("pause, resume and takeover persist through page refresh", async ({ page, request }) => {
  test.setTimeout(60_000);
  const created = await createBook(request, "recovery");
  await page.goto("/");
  await page.getByRole("button", { name: "打开书架切换作品" }).click();
  await page.getByPlaceholder("搜索书名、题材或下一步").fill(created.book.title);
  await page.locator(".ant-card").filter({ hasText: created.book.title }).getByRole("button", { name: "打开" }).click();

  await page.getByRole("button", { name: "暂停" }).click();
  await expect(page.getByRole("button", { name: "恢复生成" })).toBeVisible();
  const workspaceResponsePromise = page.waitForResponse((response) => response.url().endsWith("/api/workspace"));
  await page.reload();
  const reloadedWorkspaceResponse = await workspaceResponsePromise;
  const reloadedWorkspace = await reloadedWorkspaceResponse.json();
  expect(reloadedWorkspace.books.some((book: { id: string }) => book.id === created.book.id)).toBeTruthy();
  await expect(page.getByRole("button", { name: "恢复生成" })).toBeVisible();
  await page.getByRole("button", { name: "恢复生成" }).click();
  await expect(page.getByRole("button", { name: "暂停" })).toBeVisible();

  const [takeoverResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/generation/takeover") && response.request().method() === "POST"),
    page.getByRole("button", { name: "接管章节" }).click()
  ]);
  const takeover = await takeoverResponse.json();
  expect(takeover.generationState.status).toBe("paused");
  await expect(page.getByRole("heading", { name: "章节" })).toBeVisible();
  await page.reload();
  await page.locator(".sidebar-link").filter({ hasText: "生成" }).click();
  await expect(page.getByRole("button", { name: "恢复生成" })).toBeVisible();
  await expect(page.getByText(/作者接管/).first()).toBeVisible();
});

test("review page keeps empty memory candidates stable and uses the review account", async ({ page, request }) => {
  test.setTimeout(90_000);
  const screenshotDir = resolve("output/playwright/state-audit");
  await mkdir(screenshotDir, { recursive: true });
  const { reviewAccountId } = await installControlledAccounts(request);
  const created = await createBook(request, "review-role");
  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.getByRole("button", { name: /audit 审稿/ }).click();

  await expect(page.getByText("记忆更新候选加载失败")).toHaveCount(0);
  await expect(page.getByText("当前章节还没有可直接写入长期记忆的候选，先完成修复或重新审稿。")).toBeVisible();
  await page.getByRole("button", { name: "AI 生成修复方案" }).click();
  await expect(page.getByText("审核角色生成的修复候选。", { exact: true })).toBeVisible();
  await page.screenshot({
    path: resolve(screenshotDir, "review-repair-desktop.png"),
    fullPage: true
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "review-repair-mobile.png"),
    fullPage: true
  });

  const settings = await json(await request.get(`${apiBase}/api/ai/settings`));
  const reviewEvent = settings.usageEvents.find(
    (event: { role: string; action: string }) =>
      event.role === "review" && event.action === "生成修复方案"
  );
  expect(reviewEvent.accountId).toBe(reviewAccountId);
  expect(reviewEvent.totalTokens).toBeGreaterThan(0);
});

test("export check result stays readable on desktop and mobile", async ({ page, request }) => {
  const screenshotDir = resolve("output/playwright/state-audit");
  await mkdir(screenshotDir, { recursive: true });
  const created = await createBook(request, "export-state-audit");
  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "导出" }).click();
  await page.getByRole("button", { name: "检查正文" }).click();
  await expect(page.getByText("等待导出检查", { exact: true })).toBeHidden({ timeout: 30_000 });
  await page.screenshot({
    path: resolve(screenshotDir, "export-checked-desktop.png"),
    fullPage: true
  });

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "export-checked-mobile.png"),
    fullPage: true
  });
});

test("operation run records stay readable across viewports", async ({ page, request }) => {
  test.setTimeout(90_000);
  const screenshotDir = resolve("output/playwright/state-audit");
  await mkdir(screenshotDir, { recursive: true });
  await installControlledAccounts(request);
  const created = await createBook(request, "operations-state-audit");
  await json(await request.post(`${apiBase}/api/books/${encodeURIComponent(created.book.id)}/generation/continue`, {
    data: { bookId: created.book.id, requestId: `operations-audit-${Date.now()}` }
  }));

  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "更多" }).click();
  await page.getByText("运行记录", { exact: true }).click();
  await expect(page.locator(".more-item-card").first()).toBeVisible();
  const runCardText = await page.locator(".more-item-card").first().innerText();
  expect(runCardText).not.toMatch(/run_\d|generation-candidates|\.json/);
  await page.screenshot({
    path: resolve(screenshotDir, "operations-runs-desktop.png"),
    fullPage: true
  });

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "operations-runs-mobile.png"),
    fullPage: true
  });
});

test("quality references stay separate from hard blockers on the writing page", async ({ page, request }) => {
  test.setTimeout(90_000);
  const created = await createBook(request, "gate-repair");
  const bookId = created.book.id;
  const generationPath = `${apiBase}/api/books/${encodeURIComponent(bookId)}/generation`;
  await installControlledAccounts(request);
  await json(await request.post(`${apiBase}/api/books/${encodeURIComponent(bookId)}/materials`, {
    data: {
      id: "hard-world-rule",
      bookId,
      type: "设定",
      title: "录音规则",
      summary: "调查期间禁止销毁原始录音。",
      influence: "原始录音必须保留到终局。",
      related: ["世界设定确认记录"],
      confidence: 98,
      details: { "规则": "禁止：销毁原始录音" }
    }
  }));
  const directions = await json(await request.post(`${generationPath}/continue`, { data: { bookId, requestId: `gate-directions-${Date.now()}` } }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId, optionId: directions.generationState.candidateOptions[0].id } }));
  await json(await request.post(`${generationPath}/continue`, { data: { bookId, requestId: `gate-long-form-${Date.now()}` } }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));
  await json(await request.post(`${generationPath}/continue`, { data: { bookId, requestId: `gate-blueprint-${Date.now()}` } }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));
  await json(await request.post(`${generationPath}/continue`, { data: { bookId, requestId: `gate-contract-${Date.now()}` } }));
  await json(await request.post(`${generationPath}/confirm`, { data: { bookId } }));
  const referenceDraft = `# 第一章 试音\n\n${"这让他意识到，林澈必须保留原始录音并沿站台追查声纹；命运的齿轮仿佛转动，新的证据迫使他改变判断。".repeat(120)}\n\n新的录音在结尾发出警告。`;
  const openWritingPage = async () => {
    await page.goto("/");
    await page.getByRole("button", { name: "打开书架切换作品" }).click();
    await page.getByPlaceholder("搜索书名、题材或下一步").fill(created.book.title);
    await page.locator(".ant-card").filter({ hasText: created.book.title }).getByRole("button", { name: "打开" }).click();
    await expect.poll(() => page.evaluate(() => localStorage.getItem("open-novel-active-book"))).toBe(bookId);
    await page.reload();
    await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  };
  await openWritingPage();
  await page.locator(".chapter-editor").fill(referenceDraft);
  const referenceSaveResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/draft") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "保存草稿" }).click();
  expect((await referenceSaveResponsePromise).ok()).toBeTruthy();
  await expect(page.locator(".chapter-editor")).toHaveValue(referenceDraft);
  const [referenceGateResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate") && response.request().method() === "POST"),
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate/recovery") && response.request().method() === "GET"),
    page.getByRole("button", { name: "接收前检查" }).click()
  ]);
  const referenceGate = await referenceGateResponse.json();
  expect(referenceGate.gate.issues.some((issue: { type: string }) => issue.type === "anti_ai_trace")).toBeTruthy();
  await expect(page.getByText("风险参考", { exact: true })).toBeVisible();
  await expect(page.getByText("仅供判断风险，不单独阻止接收。")).toBeVisible();

  const blockedDraft = "# 第一章\n\n主角为了掩盖行踪，当场销毁原始录音。";
  await page.locator(".chapter-editor").fill(blockedDraft);
  const blockedSaveResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/draft") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "保存草稿" }).click();
  expect((await blockedSaveResponsePromise).ok()).toBeTruthy();
  await expect(page.locator(".chapter-editor")).toHaveValue(blockedDraft);
  const [hardGateResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate") && response.request().method() === "POST"),
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate/recovery") && response.request().method() === "GET"),
    page.getByRole("button", { name: "接收前检查" }).click()
  ]);
  const hardGate = await hardGateResponse.json();
  expect(hardGate.gate.status).toBe("block");
  expect(hardGate.gate.issues.some((issue: { severity: string }) => issue.severity === "blocker")).toBeTruthy();

  const repaired = `# 第一章 试音\n\n${"林澈沿着雨夜站台追查异常声纹，阻力迫使他改变选择并承担暴露行踪的代价。".repeat(180)}\n\n结尾时，新的录音证据改变了下一章方向。`;
  await page.locator(".chapter-editor").fill(repaired);
  const repairedSaveResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/draft") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "保存草稿" }).click();
  expect((await repairedSaveResponsePromise).ok()).toBeTruthy();
  const [recheckedResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate") && response.request().method() === "POST"),
    page.waitForResponse((response) => response.url().endsWith("/chapters/001/gate/recovery") && response.request().method() === "GET"),
    page.getByRole("button", { name: "接收前检查" }).click()
  ]);
  const rechecked = await recheckedResponse.json();
  expect(rechecked.gate.issues.some((issue: { type: string }) => issue.type === "world_rule_conflict")).toBeFalsy();
  const acceptResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/accept") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "确认接收" }).click();
  const accepted = await (await acceptResponsePromise).json();
  expect(accepted.chapter.status).toBe("完成");
});

test("full auto resumes from the page, completes three chapters and exports the manuscript", async ({ page, request }) => {
  test.setTimeout(180_000);
  const created = await createBook(request, "three-chapter-export");
  const bookId = created.book.id;
  await installControlledAccounts(request);
  await prepareConfirmedBlueprint(request, bookId, "three-chapter");
  await openBook(page, created.book.title);

  await page.getByText("全自动", { exact: true }).click();
  await page.getByRole("spinbutton", { name: "本次目标章节数" }).fill("3");
  const modeResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/generation/mode") && response.request().method() === "PUT"
  );
  await page.getByRole("button", { name: "保存设置" }).click();
  const modeResponse = await modeResponsePromise;
  expect(modeResponse.ok()).toBeTruthy();
  expect(modeResponse.request().postDataJSON()).toMatchObject({
    interventionMode: "full_auto",
    batchTarget: 3,
    autoStepLimit: 29
  });
  await page.getByRole("button", { name: "暂停" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "恢复生成" })).toBeVisible();
  await restartBackend();
  await page.reload();
  await expect(page.getByText(created.book.title).first()).toBeVisible();
  await page.locator(".hero-panel").getByRole("button", { name: "恢复生成" }).click();
  const generationResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/generation/continue") && response.request().method() === "POST"
  );
  await page.locator(".hero-panel").getByRole("button", { name: "继续生成" }).click();
  const generationResult = await (await generationResponsePromise).json();
  expect(generationResult.book.chapters).toHaveLength(3);
  expect(generationResult.book.chapters.every((chapter: { status: string }) => chapter.status === "完成")).toBeTruthy();
  await expect(page.getByText(/3\s*\/\s*3\s*章/).first()).toBeVisible({ timeout: 120_000 });

  await page.locator(".sidebar-link").filter({ hasText: "导出" }).click();
  const exportCheckResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/exports/check") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "检查正文" }).click();
  const exportCheckResponse = await exportCheckResponsePromise;
  expect(exportCheckResponse.ok()).toBeTruthy();
  const exportCheck = await exportCheckResponse.json();
  expect(exportCheck.readiness.kind).toBe("正文");
  await expect(page.getByText("等待导出检查", { exact: true })).toBeHidden({ timeout: 30_000 });
  await expect(page.getByText("当前范围：全书。生成前会保留未处理风险提示。")).toBeVisible({ timeout: 30_000 });
  const generateManuscriptButton = page.getByRole("button", { name: "生成正文" });
  await expect(generateManuscriptButton).toBeEnabled({ timeout: 30_000 });
  await generateManuscriptButton.click();
  await expect(page.getByRole("heading", { name: "manuscript.txt" })).toBeVisible();
});

test("AI model menu stays readable on desktop and mobile viewports", async ({ page, request }) => {
  await installControlledAccounts(request);
  const screenshotDir = resolve("output/playwright");
  await mkdir(screenshotDir, { recursive: true });

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/");
  await page.locator(".sidebar-link").filter({ hasText: "AI 模型" }).click();
  await page.getByRole("tab", { name: "AI 账号" }).click();
  await expect(page.getByRole("heading", { name: "AI 账号" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Token 使用量" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  const sidebarBox = await page.locator(".app-sidebar").boundingBox();
  const topbarBox = await page.locator(".topbar").boundingBox();
  expect(sidebarBox && topbarBox).toBeTruthy();
  expect(Math.abs((topbarBox?.x ?? 0) - ((sidebarBox?.x ?? 0) + (sidebarBox?.width ?? 0)))).toBeLessThan(1);
  await page.screenshot({
    path: resolve(screenshotDir, "ai-accounts-desktop.png"),
    fullPage: true
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".ai-account-table")).toBeHidden();
  await expect(page.locator(".ai-account-mobile-card")).toHaveCount(2);
  await expect(page.locator(".ai-usage-table")).toBeHidden();
  await expect(page.locator(".ai-usage-mobile-list")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "ai-accounts-mobile.png"),
    fullPage: true
  });

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.locator(".sidebar-link").filter({ hasText: "我的模型" }).click();
  await expect(page.getByRole("main").getByRole("heading", { name: "我的模型" })).toBeVisible();
  await expect(page.getByText("工作区公共模型")).toBeVisible();
  await expect(page.getByRole("button", { name: "新增模型" }).first()).toBeVisible();
  await expect(page.locator(".model-library-list .ant-skeleton")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "model-center-desktop.png"),
    fullPage: true
  });
  await page.locator(".model-library-page").screenshot({
    path: resolve(screenshotDir, "model-library-panel-desktop.png")
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("main").getByRole("heading", { name: "我的模型" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新增模型" }).first()).toBeVisible();
  const templateOptions = page.locator(".model-template-option");
  expect(await templateOptions.evaluateAll((items) => items.filter((item) => getComputedStyle(item).display !== "none").length)).toBe(6);
  await page.getByRole("button", { name: "查看全部 14 种模板" }).click();
  await expect(page.getByRole("button", { name: "使用 民俗恐怖怪谈 模板" })).toBeVisible();
  await page.getByRole("button", { name: "收起模板" }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "model-center-mobile.png"),
    fullPage: true
  });
});

test("all primary pages stay inside the workspace across responsive viewports", async ({ page, request }) => {
  test.setTimeout(180_000);
  const created = await createBook(request, "responsive-ui-audit");
  const screenshotDir = resolve("output/playwright/ui-audit");
  await mkdir(screenshotDir, { recursive: true });
  const primaryPages = [
    { label: "AI 模型", slug: "ai-model" },
    { label: "书架", slug: "shelf" },
    { label: "我的模型", slug: "model-library" },
    { label: "生成", slug: "generation" },
    { label: "章节", slug: "writing" },
    { label: "资料", slug: "library" },
    { label: "审稿", slug: "review" },
    { label: "导出", slug: "export" },
    { label: "更多", slug: "more" }
  ];
  const assertCurrentPageBounds = async () => {
    const bounds = await page.evaluate(() => {
      const visible = (element: Element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const tracked = Array.from(document.querySelectorAll(
        ".workspace, .single-page, .page-grid, .responsive-detail-page > .side-column, .shelf-detail-column, .library-side-column, .writing-side-column"
      ))
        .filter(visible)
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return { className: element.className, left: rect.left, right: rect.right };
        });
      return {
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        tracked
      };
    });
    expect(bounds.documentWidth).toBeLessThanOrEqual(bounds.viewportWidth + 1);
    for (const item of bounds.tracked) {
      expect(item.left, item.className).toBeGreaterThanOrEqual(-1);
      expect(item.right, item.className).toBeLessThanOrEqual(bounds.viewportWidth + 1);
    }
  };
  const assertNoLayoutScrollers = async () => {
    const offenders = await page.evaluate(() => {
      const selectors = [
        ".sidebar-nav",
        ".generation-page",
        ".generation-scroll-card > .ant-card-body",
        ".responsive-detail-page > .side-column",
        ".shelf-detail-column",
        ".library-side-column",
        ".model-list",
        ".model-side-column",
        ".model-training-grid > .main-column",
        ".model-training-grid > .side-column",
        ".model-library-list",
        ".model-library-detail"
      ];
      return Array.from(document.querySelectorAll(selectors.join(",")))
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
        })
        .map((element) => {
          const style = getComputedStyle(element);
          return {
            className: element.className,
            overflowY: style.overflowY,
            clientHeight: element.clientHeight,
            scrollHeight: element.scrollHeight
          };
        })
        .filter((item) => ["auto", "scroll"].includes(item.overflowY));
    });
    expect(offenders).toEqual([]);
  };
  const openPrimaryPage = async (item: { label: string; slug: string }, mobile = false) => {
    if (!mobile) {
      await page.locator(".sidebar-link").filter({ hasText: item.label }).click();
    } else if (["AI 模型", "书架", "生成", "章节"].includes(item.label)) {
      await page.locator(".mobile-tab").filter({ hasText: item.label }).click();
    } else {
      await page.locator(".mobile-tab").filter({ hasText: "更多" }).click();
      await page.getByRole("menuitem").filter({ hasText: item.label }).click();
    }
    await expect(page.locator(".workspace")).toBeVisible();
    await expect(page.locator(".page-loading")).toHaveCount(0);
    if (item.slug === "model-library") {
      await expect(page.locator(".model-library-list .ant-skeleton")).toHaveCount(0);
    }
  };

  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1280, height: 720 },
    { width: 1100, height: 720 },
    { width: 1024, height: 768 }
  ]) {
    await page.setViewportSize(viewport);
    await openBook(page, created.book.title);
    for (const item of primaryPages) {
      await openPrimaryPage(item);
      await assertCurrentPageBounds();
      await assertNoLayoutScrollers();
      if (viewport.width === 1920 || viewport.width === 1280) {
        await page.screenshot({
          path: resolve(screenshotDir, `${item.slug}-${viewport.width}x${viewport.height}.png`),
          fullPage: true
        });
      }
    }
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await openBook(page, created.book.title);
  for (const item of primaryPages) {
    await openPrimaryPage(item, true);
    await assertCurrentPageBounds();
    await assertNoLayoutScrollers();
    await page.screenshot({
      path: resolve(screenshotDir, `${item.slug}-390x844.png`),
      fullPage: true
    });
  }
});

test("desktop sidebar adapts to low-height editor viewports without overlap", async ({ page, request }) => {
  const created = await createBook(request, "sidebar-low-height");
  const screenshotDir = resolve("output/playwright/ui-audit/sidebar");
  await mkdir(screenshotDir, { recursive: true });

  for (const viewport of [
    { width: 1280, height: 1100 },
    { width: 1280, height: 1000 },
    { width: 1280, height: 900 },
    { width: 1280, height: 720 },
    { width: 1440, height: 560 },
    { width: 1280, height: 600 },
    { width: 1100, height: 600 }
  ]) {
    await page.setViewportSize(viewport);
    await openBook(page, created.book.title);
    const layout = await page.evaluate(() => {
      const sidebar = document.querySelector(".app-sidebar")?.getBoundingClientRect();
      const nav = document.querySelector(".sidebar-nav")?.getBoundingClientRect();
      const footerElement = document.querySelector(".sidebar-footer-panel");
      const footer = footerElement && getComputedStyle(footerElement).display !== "none"
        ? footerElement.getBoundingClientRect()
        : null;
      const links = Array.from(document.querySelectorAll(".sidebar-link")).map((element) => {
        const rect = element.getBoundingClientRect();
        return { top: rect.top, bottom: rect.bottom };
      });
      return {
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        sidebar: sidebar ? { left: sidebar.left, right: sidebar.right, top: sidebar.top, bottom: sidebar.bottom, width: sidebar.width } : null,
        nav: nav ? { top: nav.top, bottom: nav.bottom } : null,
        footer: footer ? { top: footer.top, bottom: footer.bottom } : null,
        links
      };
    });
    expect(layout.sidebar).not.toBeNull();
    expect(layout.sidebar?.left).toBeGreaterThanOrEqual(0);
    expect(layout.sidebar?.right).toBeLessThanOrEqual(layout.viewportWidth + 1);
    expect(layout.sidebar?.bottom).toBeLessThanOrEqual(layout.viewportHeight + 1);
    expect(layout.nav?.bottom ?? 0).toBeLessThanOrEqual((layout.footer?.top ?? layout.viewportHeight) + 1);
    expect(layout.footer?.bottom ?? 0).toBeLessThanOrEqual((layout.sidebar?.bottom ?? layout.viewportHeight) + 1);
    await expect(page.getByText("全局", { exact: true })).toBeVisible();
    await expect(page.getByText("当前书", { exact: true }).first()).toBeVisible();
    await expect(page.locator(".sidebar-link-meta").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /深色模式|浅色模式/ })).toHaveCount(0);
    await expect(page.locator(".sidebar-switcher .ant-progress")).toBeVisible();
    for (const link of layout.links) {
      expect(link.top).toBeGreaterThanOrEqual((layout.nav?.top ?? 0) - 1);
      expect(link.bottom).toBeLessThanOrEqual((layout.nav?.bottom ?? layout.viewportHeight) + 1);
      expect(link.bottom).toBeLessThanOrEqual((layout.sidebar?.bottom ?? layout.viewportHeight) + 1);
    }
    await page.screenshot({
      animations: "disabled",
      path: resolve(screenshotDir, `sidebar-${viewport.width}x${viewport.height}.png`)
    });
  }
});

test("desktop sidebar can collapse, expand and preserve the preference", async ({ page, request }) => {
  const created = await createBook(request, "sidebar-collapse");
  const screenshotDir = resolve("output/playwright/ui-audit/sidebar");
  await mkdir(screenshotDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 560 });
  await openBook(page, created.book.title);

  const sidebar = page.locator(".app-sidebar");
  await expect(sidebar).not.toHaveClass(/is-collapsed/);
  const expandedWidth = (await sidebar.boundingBox())?.width ?? 0;
  expect(expandedWidth).toBeGreaterThan(200);

  await page.getByRole("button", { name: "收起左侧导航" }).click();
  await expect(sidebar).toHaveClass(/is-collapsed/);
  await expect.poll(async () => (await sidebar.boundingBox())?.width ?? 0).toBeLessThanOrEqual(73);
  const collapsedLayout = await page.evaluate(() => {
    const sidebarRect = document.querySelector(".app-sidebar")?.getBoundingClientRect();
    return {
      sidebarBottom: sidebarRect?.bottom ?? window.innerHeight,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      links: Array.from(document.querySelectorAll(".sidebar-link")).map((element) => {
        const rect = element.getBoundingClientRect();
        return { top: rect.top, bottom: rect.bottom };
      })
    };
  });
  expect(collapsedLayout.documentWidth).toBeLessThanOrEqual(collapsedLayout.viewportWidth + 1);
  for (const link of collapsedLayout.links) {
    expect(link.top).toBeGreaterThanOrEqual(0);
    expect(link.bottom).toBeLessThanOrEqual(collapsedLayout.sidebarBottom + 1);
  }
  await page.mouse.move(400, 300);
  await page.screenshot({
    animations: "disabled",
    path: resolve(screenshotDir, "sidebar-collapsed-1440x560.png")
  });
  await page.getByRole("button", { name: "章节", exact: true }).click();
  await expect(page.getByRole("heading", { name: "章节" })).toBeVisible();

  await page.reload();
  await expect(sidebar).toHaveClass(/is-collapsed/);
  await expect.poll(async () => (await sidebar.boundingBox())?.width ?? 0).toBeLessThanOrEqual(73);

  await page.getByRole("button", { name: "展开左侧导航" }).click();
  await expect(sidebar).not.toHaveClass(/is-collapsed/);
  await expect.poll(async () => (await sidebar.boundingBox())?.width ?? 0).toBeGreaterThan(200);
});

test("writing and library non-default panels stay readable across viewports", async ({ page, request }) => {
  test.setTimeout(120_000);
  const created = await createBook(request, "panel-ui-audit");
  await openBook(page, created.book.title);
  const screenshotDir = resolve("output/playwright/state-audit");
  await mkdir(screenshotDir, { recursive: true });

  const assertPageFits = async () => {
    const layout = await page.evaluate(() => ({
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth
    }));
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth + 1);
  };

  for (const viewport of [
    { width: 1280, height: 720, suffix: "desktop" },
    { width: 390, height: 844, suffix: "mobile" }
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    if (viewport.width > 720) {
      await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
    } else {
      await page.locator(".mobile-tab").filter({ hasText: "章节" }).click();
    }
    const chapterTabs = page.getByRole("tablist", { name: "章节辅助面板" });
    const chapterAssist = page.getByLabel("章节辅助内容");
    for (const label of ["任务", "资料", "人物", "线索", "审阅", "经验", "创意", "上下文", "场景"]) {
      await chapterTabs.getByRole("tab", { name: label }).click();
      await expect(chapterAssist).not.toContainText("正在读取");
      await assertPageFits();
      await page.screenshot({
        path: resolve(screenshotDir, `writing-${label}-${viewport.suffix}.png`),
        fullPage: true
      });
    }

    if (viewport.width > 720) {
      await page.locator(".sidebar-link").filter({ hasText: "资料" }).click();
    } else {
      await page.locator(".mobile-tab").filter({ hasText: "更多" }).click();
      await page.getByRole("menuitem").filter({ hasText: "资料" }).click();
    }
    await page.getByRole("button", { name: "AI 助手" }).click();
    await expect(page.getByText("AI 资料助手", { exact: true })).toBeVisible();
    await assertPageFits();
    await page.screenshot({
      path: resolve(screenshotDir, `library-ai-${viewport.suffix}.png`),
      fullPage: true
    });

    await page.getByRole("button", { name: "返回详情" }).click();
    await page.getByRole("button", { name: "新增人物" }).click();
    await expect(page.getByRole("heading", { name: "新增人物" })).toBeVisible();
    await assertPageFits();
    await page.screenshot({
      path: resolve(screenshotDir, `library-editor-${viewport.suffix}.png`),
      fullPage: true
    });
  }
});

test("library long material collections stay structured across viewports", async ({ page, request }) => {
  test.setTimeout(90_000);
  const created = await createBook(request, "library-long-data");
  for (const index of Array.from({ length: 21 }, (_, itemIndex) => itemIndex)) {
    await json(await request.post(
      `${apiBase}/api/books/${encodeURIComponent(created.book.id)}/materials`,
      {
        data: {
          id: `audit-character-${index + 1}`,
          bookId: created.book.id,
          type: "人物",
          title: `人物资料 ${String(index + 1).padStart(2, "0")}`,
          summary: `用于长列表验收的人物摘要 ${index + 1}，包含目标、秘密和当前章节影响。`,
          influence: `第 ${index + 1} 条人物资料对当前章节的影响。`,
          related: [`人物关系 ${index + 1}`],
          confidence: 80,
          details: {
            goal: `人物目标 ${index + 1}`,
            secret: `人物秘密 ${index + 1}`
          }
        }
      }
    ));
  }
  const screenshotDir = resolve("output/playwright/state-audit");
  await mkdir(screenshotDir, { recursive: true });

  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "资料" }).click();
  const showAllMaterials = page.getByRole("button", { name: "查看全部资料" });
  if (await showAllMaterials.isVisible()) {
    await showAllMaterials.click();
  }
  await expect(page.locator(".material-summary-list")).toBeVisible();
  await expect(page.locator(".material-list-pagination")).toBeVisible();
  await expect(page.getByText("[已隐藏敏感内容]", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: resolve(screenshotDir, "library-long-data-desktop.png"),
    fullPage: true
  });

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "library-long-data-mobile.png"),
    fullPage: true
  });
});

test("long forms and confirmation dialogs stay usable across viewports", async ({ page, request }) => {
  test.setTimeout(90_000);
  await installControlledAccounts(request);
  const created = await createBook(request, "dialog-ui-audit");
  const screenshotDir = resolve("output/playwright/state-audit/dialogs");
  await mkdir(screenshotDir, { recursive: true });

  const assertDialogFits = async (name: string) => {
    const dialog = page.getByRole("dialog", { name });
    await expect(dialog).toBeVisible();
    const bounds = await dialog.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight
      };
    });
    expect(bounds.left).toBeGreaterThanOrEqual(0);
    expect(bounds.right).toBeLessThanOrEqual(bounds.viewportWidth + 1);
    expect(bounds.top).toBeGreaterThanOrEqual(0);
    return dialog;
  };

  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "书架" }).click();
  await page.getByRole("button", { name: "新建作品" }).click();
  let dialog = await assertDialogFits("新建作品");
  await dialog.getByPlaceholder("作品名称").fill("桌面弹窗验收作品");
  await dialog.getByRole("button", { name: "下一步" }).click();
  await dialog.screenshot({
    path: resolve(screenshotDir, "new-book-desktop.png")
  });
  await dialog.getByRole("button", { name: "Close", exact: true }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".mobile-tab").filter({ hasText: "书架" }).click();
  await page.getByRole("button", { name: "新建作品" }).click();
  dialog = await assertDialogFits("新建作品");
  await dialog.getByPlaceholder("作品名称").fill("移动弹窗验收作品");
  await dialog.getByRole("button", { name: "下一步" }).click();
  await expect(dialog.getByRole("button", { name: "上一步" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "下一步" })).toBeVisible();
  await dialog.screenshot({
    path: resolve(screenshotDir, "new-book-mobile.png")
  });
  await dialog.getByRole("button", { name: "Close", exact: true }).click();

  await page.locator(".mobile-tab").filter({ hasText: "AI 模型" }).click();
  await page.getByRole("tab", { name: "AI 账号" }).click();
  await page.getByRole("button", { name: "新增账号" }).click();
  dialog = await assertDialogFits("新增 AI 账号");
  await expect(dialog.getByRole("button", { name: "保存账号" })).toBeVisible();
  await dialog.screenshot({
    path: resolve(screenshotDir, "ai-account-mobile.png")
  });
  await dialog.getByRole("button", { name: "Close", exact: true }).click();

  await json(await request.post(
    `${apiBase}/api/books/${encodeURIComponent(created.book.id)}/generation/continue`,
    { data: { bookId: created.book.id, requestId: `dialog-candidate-${Date.now()}` } }
  ));
  await openBook(page, created.book.title);
  await page.locator(".mobile-tab").filter({ hasText: "生成" }).click();
  await page.getByRole("button", { name: "重新生成" }).click();
  dialog = await assertDialogFits("重新生成当前阶段候选？");
  await expect(dialog.getByRole("button", { name: "重新生成" })).toBeVisible();
});

test("draft history modal stays inside the viewport on desktop and mobile", async ({ page, request }) => {
  const created = await createBook(request, "draft-history-modal");
  const screenshotDir = resolve("output/playwright/state-audit/dialogs");
  await mkdir(screenshotDir, { recursive: true });

  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  const editor = page.locator(".chapter-editor");
  const initialDraft = await editor.inputValue();
  await editor.fill(`${initialDraft}\n\n补充一段用于历史版本弹窗验收的正文。`);
  const saveButton = page.getByRole("button", { name: "保存草稿" });
  const saveResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/draft") && response.request().method() === "POST"
  );
  await saveButton.click();
  expect((await saveResponsePromise).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name: "历史版本" })).toBeEnabled();

  const assertHistoryDialog = async () => {
    const historyDialog = page.getByRole("dialog", { name: "本地历史版本" });
    await expect(historyDialog).toBeVisible();
    await expect(historyDialog.locator(".draft-history-preview")).toBeVisible();
    await expect(historyDialog.getByRole("button", { name: "恢复到编辑区" })).toBeVisible();
    const viewport = page.viewportSize();
    const expectedWidth = Math.min(600, (viewport?.width ?? 1280) - 30);
    await expect.poll(
      () => historyDialog.evaluate((element) => element.getBoundingClientRect().width)
    ).toBeGreaterThanOrEqual(expectedWidth);
    const bounds = await historyDialog.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: rect.top,
        bottom: rect.bottom,
        left: rect.left,
        right: rect.right,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight
      };
    });
    expect(bounds.top).toBeGreaterThanOrEqual(12);
    expect(bounds.bottom).toBeLessThanOrEqual(bounds.viewportHeight - 12);
    expect(bounds.left).toBeGreaterThanOrEqual(12);
    expect(bounds.right).toBeLessThanOrEqual(bounds.viewportWidth - 12);
    return historyDialog;
  };

  await page.getByRole("button", { name: "历史版本" }).click();
  let historyDialog = await assertHistoryDialog();
  await historyDialog.screenshot({
    animations: "disabled",
    path: resolve(screenshotDir, "draft-history-desktop.png")
  });
  await historyDialog.getByRole("button", { name: "Close", exact: true }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "历史版本" }).click();
  historyDialog = await assertHistoryDialog();
  await historyDialog.screenshot({
    animations: "disabled",
    path: resolve(screenshotDir, "draft-history-mobile.png")
  });
});

test("writing progress follows the live word target instead of the draft status", async ({ page, request }) => {
  const created = await createBook(request, "writing-word-progress");
  const screenshotDir = resolve("output/playwright/state-audit/writing");
  await mkdir(screenshotDir, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 720 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();

  const draftText = "山门外的雨越下越大，林澈握紧录音笔，沿着石阶追向那道刚刚消失的人影。".repeat(2);
  const expectedProgress = Math.round((draftText.trim().length / 3000) * 100);
  const wordProgressCircle = page.locator('.writing-editor-pane [role="progressbar"].ant-progress-circle');
  await page.locator(".chapter-editor").fill(draftText);
  await expect(wordProgressCircle).toContainText(`${expectedProgress}%`);
  await expect(page.locator(".chapter-rail-item.active .chapter-rail-meta")).toContainText(`字数 ${expectedProgress}%`);

  const saveResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/chapters/001/draft") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "保存草稿" }).click();
  expect((await saveResponsePromise).ok()).toBeTruthy();
  await page.reload();
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  await expect(page.locator(".chapter-rail-item.active .chapter-rail-meta")).toHaveText(`草稿 · 字数 ${expectedProgress}%`);
  await expect(page.locator('.writing-editor-pane [role="progressbar"].ant-progress-circle')).toContainText(`${expectedProgress}%`);
  await page.locator(".writing-editor-pane").screenshot({
    animations: "disabled",
    path: resolve(screenshotDir, "writing-progress-real-word-count.png")
  });
});

test("writing workspace keeps equal author and AI panes with reference content at the right edge", async ({ page, request }) => {
  const created = await createBook(request, "writing-ultrawide");
  await installControlledAccounts(request);
  const screenshotDir = resolve("output/playwright/state-audit");
  await mkdir(screenshotDir, { recursive: true });
  await page.setViewportSize({ width: 2048, height: 1152 });
  await openBook(page, created.book.title);
  await page.locator(".sidebar-link").filter({ hasText: "章节" }).click();
  await expect(page.locator(".writing-page-grid")).toBeVisible();
  await expect(page.locator(".writing-editor-pane")).toBeVisible();
  await expect(page.locator(".writing-candidate-pane")).toBeVisible();
  await expect(page.locator(".writing-side-column")).toBeVisible();
  await page.getByRole("button", { name: "准备本章" }).click();
  await expect(page.locator(".chapter-prepare-status .ant-badge-status-text")).toBeVisible();
  await page.getByRole("button", { name: "AI 续写" }).click();
  await expect(page.getByText("修改意见", { exact: true })).toBeVisible();

  const layout = await page.evaluate(() => {
    const workspace = document.querySelector(".workspace")!.getBoundingClientRect();
    const grid = document.querySelector(".writing-page-grid")!.getBoundingClientRect();
    const editor = document.querySelector(".writing-editor-pane")!.getBoundingClientRect();
    const candidate = document.querySelector(".writing-candidate-pane")!.getBoundingClientRect();
    const references = document.querySelector(".writing-side-column")!.getBoundingClientRect();
    const preparation = document.querySelector(".chapter-prepare-card")!.getBoundingClientRect();
    return {
      workspaceLeft: workspace.left,
      workspaceRight: workspace.right,
      gridLeft: grid.left,
      gridRight: grid.right,
      editorWidth: editor.width,
      candidateWidth: candidate.width,
      editorBottom: editor.bottom,
      candidateBottom: candidate.bottom,
      referencesRight: references.right,
      preparationHeight: preparation.height
    };
  });

  expect(layout.gridLeft).toBeGreaterThanOrEqual(layout.workspaceLeft);
  expect(layout.workspaceRight - layout.gridRight).toBeLessThanOrEqual(24);
  expect(layout.workspaceRight - layout.referencesRight).toBeLessThanOrEqual(24);
  expect(Math.abs(layout.editorWidth - layout.candidateWidth)).toBeLessThanOrEqual(2);
  expect(Math.abs(layout.editorBottom - layout.candidateBottom)).toBeLessThanOrEqual(2);
  expect(layout.preparationHeight).toBeLessThanOrEqual(132);
  await expect(page.locator(".writing-editor-scroll")).toHaveCSS("overflow-y", "auto");
  await expect(page.locator(".writing-ai-scroll")).toHaveCSS("overflow-y", "auto");
  await expect(page.locator(".writing-side-scroll")).toHaveCSS("overflow-y", "auto");
  await expect(page.locator(".writing-ai-footer")).toContainText("应用到草稿");
  await expect(page.locator(".writing-side-column")).not.toContainText("AI 工作区");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({
    path: resolve(screenshotDir, "writing-ultrawide-2048x1152.png"),
    fullPage: true
  });
});
