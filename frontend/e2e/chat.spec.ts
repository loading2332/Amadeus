import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/static/");
  await expect(page.getByText("Amadeus", { exact: true }).first()).toBeVisible();
});

test("uses the bundled interface font without a chat header", async ({ page }) => {
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await expect(page.locator("main header")).toHaveCount(0);
  const fontFamily = await page.locator("body").evaluate((element) => getComputedStyle(element).fontFamily);
  expect(fontFamily).toContain("Inter Variable");
});

test("centers the empty conversation prompt and removes it after sending", async ({ page }) => {
  await visibleButton(page, "新对话").click();
  const prompt = page.getByTestId("timeline-state-content");
  await expect(prompt).toContainText("有什么想一起完成的？");

  const centerOffset = await prompt.evaluate((element) => {
    const viewport = element.closest('[data-testid="chat-timeline"]');
    if (viewport === null) throw new Error("chat timeline missing");
    const promptRect = element.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    return Math.abs(promptRect.top + promptRect.height / 2 - (viewportRect.top + viewportRect.height / 2));
  });
  expect(centerOffset).toBeLessThanOrEqual(1);

  await page.getByPlaceholder("给 Amadeus 发消息").fill("开始对话");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(prompt).toHaveCount(0);
});

test("keeps a failed message draft and sends it again in place", async ({ page }) => {
  await visibleButton(page, "新对话").click();
  let createTurnAttempts = 0;
  await page.route("**/api/messages", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    createTurnAttempts += 1;
    if (createTurnAttempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ code: "temporarily_unavailable", detail: "temporary fixture failure" }),
      });
      return;
    }
    await route.continue();
  });

  const message = "失败后仍保留的草稿";
  const input = page.getByPlaceholder("给 Amadeus 发消息");
  await input.fill(message);
  await page.getByRole("button", { name: "发送消息" }).click();

  await expect(page.getByRole("alert")).toContainText("消息未发送");
  await expect(input).toHaveValue(message);
  await page.getByRole("button", { name: "重试发送" }).click();
  await expect(page.getByText("确定性回答")).toBeVisible();
  await expect(input).toHaveValue("");
  expect(createTurnAttempts).toBe(2);
});

test("retries creating a conversation without losing the current page", async ({ page }) => {
  await page.getByRole("button", { name: "收起侧边栏" }).click();
  await expect(page.getByTestId("desktop-sidebar-shell")).toHaveCSS("width", "0px");
  let createSessionAttempts = 0;
  await page.route("**/api/sessions", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    createSessionAttempts += 1;
    if (createSessionAttempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ code: "temporarily_unavailable", detail: "temporary fixture failure" }),
      });
      return;
    }
    await route.continue();
  });

  const previousSession = new URL(page.url()).searchParams.get("session");
  await visibleButton(page, "新对话").click();
  await expect(page.getByRole("alert")).toContainText("新对话创建失败");
  await page.getByRole("button", { name: "重试新建" }).filter({ visible: true }).click();

  await expect.poll(() => new URL(page.url()).searchParams.get("session")).not.toBe(previousSession);
  expect(createSessionAttempts).toBe(2);
});

test("uses the first message summary as the durable conversation title", async ({ page }) => {
  const title = "请把本周的开发进展整理成三条摘要";
  await createConversation(page, title);

  await expect(visibleButton(page, title)).toBeVisible();
  await page.reload();
  await expect(visibleButton(page, title)).toBeVisible();
});

test("visually groups each question with its answer on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await createConversation(page, "视觉分组第一问");
  await expect(page.getByText("确定性回答")).toHaveCount(1);
  await send(page, "视觉分组第二问");
  await expect(page.getByText("确定性回答")).toHaveCount(2);

  const gaps = await page.locator('article[aria-label="一轮对话"]').evaluateAll((articles) => {
    if (articles.length !== 2) throw new Error(`expected two turns, received ${articles.length}`);
    const firstUser = articles[0].querySelector('[aria-label="你的消息"]');
    const firstAnswer = articles[0].querySelector('[aria-label="Amadeus 的回答"]');
    if (!(firstUser instanceof HTMLElement) || !(firstAnswer instanceof HTMLElement)) {
      throw new Error("turn content missing");
    }
    return {
      withinTurn: firstAnswer.getBoundingClientRect().top - firstUser.getBoundingClientRect().bottom,
      betweenTurns: articles[1].getBoundingClientRect().top - articles[0].getBoundingClientRect().bottom,
    };
  });

  expect(gaps.withinTurn).toBeLessThanOrEqual(24);
  expect(gaps.betweenTurns).toBeGreaterThanOrEqual(40);
  expect(gaps.withinTurn).toBeLessThan(gaps.betweenTurns);
});

test("centers the single-line input and highlights the whole composer", async ({ page }) => {
  await visibleButton(page, "新对话").click();
  const input = page.getByPlaceholder("给 Amadeus 发消息");
  await input.focus();

  await expect(input.locator("xpath=..//fieldset")).toHaveCSS("border-width", "0px");
  const composerShell = page.getByTestId("composer-shell");
  const primaryColor = await composerShell.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.color = "var(--mui-palette-primary-main)";
    document.body.append(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  });
  await expect(composerShell).toHaveCSS("border-color", primaryColor);
  const verticalOffset = await input.evaluate((textarea) => {
    const shell = textarea.closest('[data-testid="composer-shell"]');
    if (shell === null) throw new Error("composer shell missing");
    const inputRect = textarea.getBoundingClientRect();
    const shellRect = shell.getBoundingClientRect();
    const topGap = inputRect.top - shellRect.top;
    const bottomGap = shellRect.bottom - inputRect.bottom;
    return Math.abs(topGap - bottomGap);
  });
  expect(verticalOffset).toBeLessThanOrEqual(1);
  const leftInset = await input.evaluate((textarea) => {
    const shell = textarea.closest('[data-testid="composer-shell"]');
    if (shell === null) throw new Error("composer shell missing");
    return textarea.getBoundingClientRect().left - shell.getBoundingClientRect().left;
  });
  expect(leftInset).toBeGreaterThanOrEqual(20);

  await input.fill("第一行\n第二行\n第三行");
  const multilineBottomOffset = await input.evaluate((textarea) => {
    const inputRoot = textarea.parentElement;
    const button = document.querySelector('button[aria-label="发送消息"]');
    if (inputRoot === null || button === null) throw new Error("composer controls missing");
    return Math.abs(inputRoot.getBoundingClientRect().bottom - button.getBoundingClientRect().bottom);
  });
  expect(multilineBottomOffset).toBeLessThanOrEqual(1);
});

test("renders the composer as a floating rounded box without a full-width bar", async ({ page }) => {
  if (!(await page.getByPlaceholder("给 Amadeus 发消息").isVisible())) {
    await visibleButton(page, "新对话").click();
  }
  const composerBar = page.getByTestId("composer-bar");
  const sidebarFooter = page.getByTestId("sidebar-footer").filter({ visible: true });
  await expect(composerBar).toHaveCSS("border-top-width", "0px");
  await expect(composerBar).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");

  const composerShape = await page.getByTestId("composer-shell").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      height: rect.height,
      radius: Number.parseFloat(style.borderRadius),
      backgroundColor: style.backgroundColor,
      boxShadow: style.boxShadow,
    };
  });
  const themeControl = sidebarFooter.getByTestId("theme-mode-control");
  await expect(themeControl).toHaveText("");
  const themeShape = await themeControl.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { height: rect.height, radius: Number.parseFloat(getComputedStyle(element).borderRadius) };
  });
  expect(composerShape.radius).toBeGreaterThanOrEqual(20);
  expect(composerShape.radius).toBeLessThanOrEqual(composerShape.height / 2);
  expect(composerShape.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(composerShape.boxShadow).not.toBe("none");
  expect(themeShape.height).toBeLessThan(composerShape.height);
  expect(themeShape.radius).toBeGreaterThanOrEqual(8);

  const bottomGap = await page.getByTestId("composer-shell").evaluate(
    (element) => window.innerHeight - element.getBoundingClientRect().bottom,
  );
  expect(bottomGap).toBeGreaterThanOrEqual(24);
});

test("collapses the desktop sidebar and restores the preference", async ({ page }) => {
  const sidebar = page.getByTestId("desktop-sidebar-shell");
  await expect(sidebar).toHaveCSS("width", "280px");
  await visibleButton(page, "新对话").click();
  await expect(sidebar.getByText("今天", { exact: true })).toBeVisible();
  const main = page.locator("main");
  const expandedMainBox = await main.boundingBox();
  expect(expandedMainBox).not.toBeNull();
  await expect(main.locator("header")).toHaveCount(0);

  await page.getByRole("button", { name: "收起侧边栏" }).click();
  await page.waitForTimeout(80);
  const midAnimationWidth = await sidebar.evaluate((element) => element.getBoundingClientRect().width);
  expect(midAnimationWidth).toBeGreaterThan(0);
  expect(midAnimationWidth).toBeLessThan(280);
  await expect(sidebar).toHaveCSS("width", "0px");
  await expect(page.getByRole("navigation", { name: "会话列表" })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "展开侧边栏" })).toBeVisible();
  await expect(visibleButton(page, "新对话")).toBeVisible();
  const collapsedMainBox = await main.boundingBox();
  expect(collapsedMainBox).not.toBeNull();
  expect(collapsedMainBox!.x).toBeLessThan(expandedMainBox!.x);

  const previousSession = new URL(page.url()).searchParams.get("session");
  await visibleButton(page, "新对话").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("session")).not.toBe(previousSession);
  await expect(sidebar).toHaveCSS("width", "0px");

  await page.reload();
  await expect(sidebar).toHaveCSS("width", "0px");
  await page.getByRole("button", { name: "展开侧边栏" }).click();
  await expect(sidebar).toHaveCSS("width", "280px");
  await expect(page.getByRole("navigation", { name: "会话列表" })).toBeVisible();
});

test("keeps the shell fixed and follows a growing conversation", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 500 });
  await createConversation(page, "长对话 1");
  await expect(page.getByText("确定性回答")).toHaveCount(1);

  for (let index = 2; index <= 5; index += 1) {
    await send(page, `长对话 ${index}`);
    await expect(page.getByText("确定性回答")).toHaveCount(index);
  }

  const layout = await page.evaluate(() => {
    const sidebar = document.querySelector('[data-testid="desktop-sidebar-shell"]');
    const timeline = document.querySelector('[data-testid="chat-timeline"]');
    if (!(sidebar instanceof HTMLElement) || !(timeline instanceof HTMLElement)) {
      throw new Error("chat layout elements missing");
    }
    const sidebarRect = sidebar.getBoundingClientRect();
    return {
      viewportHeight: window.innerHeight,
      documentHeight: document.documentElement.scrollHeight,
      sidebarTop: sidebarRect.top,
      sidebarBottom: sidebarRect.bottom,
      timelineClientHeight: timeline.clientHeight,
      timelineScrollHeight: timeline.scrollHeight,
      timelineBottomGap: timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight,
    };
  });

  expect.soft(layout.documentHeight).toBe(layout.viewportHeight);
  expect.soft(layout.sidebarTop).toBe(0);
  expect.soft(layout.sidebarBottom).toBe(layout.viewportHeight);
  expect.soft(layout.timelineScrollHeight).toBeGreaterThan(layout.timelineClientHeight);
  expect.soft(layout.timelineBottomGap).toBeLessThanOrEqual(2);

  const timeline = page.getByTestId("chat-timeline");
  await timeline.evaluate((element) => element.scrollTo({ top: 0 }));
  const returnToBottom = page.getByRole("button", { name: "回到底部" });
  await expect(returnToBottom).toBeVisible();
  await expect(returnToBottom).toHaveText("");
  const returnShape = await returnToBottom.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { width: rect.width, height: rect.height, radius: Number.parseFloat(getComputedStyle(element).borderRadius) };
  });
  expect(returnShape.width).toBe(returnShape.height);
  expect(returnShape.radius).toBeGreaterThanOrEqual(returnShape.width / 2);
  await returnToBottom.hover();
  await expect(page.getByRole("tooltip", { name: "回到底部" })).toHaveCount(0);
  await timeline.evaluate((element) => {
    element.dataset.sawIntermediateReturnScroll = "false";
    element.dataset.returnButtonStayedVisible = "true";
    element.addEventListener("scroll", () => {
      const bottomGap = element.scrollHeight - element.scrollTop - element.clientHeight;
      if (bottomGap <= 2) return;
      element.dataset.sawIntermediateReturnScroll = "true";
      if (document.querySelector('button[aria-label="回到底部"]') === null) {
        element.dataset.returnButtonStayedVisible = "false";
      }
    });
  });
  await returnToBottom.click();
  await expect(returnToBottom).toHaveCount(0);
  const returnTrace = await timeline.evaluate((element) => ({
    sawIntermediateScroll: element.dataset.sawIntermediateReturnScroll,
    stayedVisible: element.dataset.returnButtonStayedVisible,
    bottomGap: element.scrollHeight - element.scrollTop - element.clientHeight,
  }));
  expect(returnTrace.sawIntermediateScroll).toBe("true");
  expect(returnTrace.stayedVisible).toBe("true");
  expect(returnTrace.bottomGap).toBeLessThanOrEqual(2);
  await page.waitForTimeout(100);
  await expect(returnToBottom).toHaveCount(0);
});

test("creates a session, streams text and tools, then restores after refresh", async ({ page }) => {
  await createConversation(page, "浏览器完成链路");
  await expect(page.getByText("lookup_fixture")).toBeVisible();
  await expect(page.getByText("已完成")).toBeVisible();
  await expect(page.getByText("确定性回答")).toBeVisible();
  await page.reload();
  await expect(page.getByText("确定性回答")).toBeVisible();
});

test("keeps slow streams isolated while switching sessions", async ({ page }) => {
  await createConversation(page, "[slow] 会话甲");
  await expect(page.getByText("慢速")).toBeVisible();
  await visibleButton(page, "新对话").click();
  await send(page, "会话乙");
  await expect(page.getByText("确定性回答")).toBeVisible();
  await visibleButton(page, "[slow] 会话甲").click();
  await expect(page.getByText("慢速回答仍在继续")).toBeVisible();
});

test("stops a turn and preserves its partial answer after refresh", async ({ page }) => {
  await createConversation(page, "[slow] 请停止");
  await expect(page.getByText("慢速")).toBeVisible();
  await page.getByRole("button", { name: "停止生成" }).click();
  await expect(page.getByText(/已停止生成/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/慢速/).last()).toBeVisible();
  await expect(page.getByText(/已停止生成/)).toBeVisible();
});

test("keeps a failed attempt and appends a successful retry", async ({ page }) => {
  await createConversation(page, "[fail] 请重试");
  const failedTurn = page.locator('article[aria-label="一轮对话"]').filter({ hasText: "[fail] 请重试" });
  await expect(failedTurn.getByText("失败前的部分回答")).toBeVisible();
  await expect(failedTurn.getByText("模型响应超时，请重试")).toBeVisible();
  await failedTurn.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("确定性回答")).toBeVisible();
  await expect(page.getByText("失败前的部分回答")).toBeVisible();
});

test("supports mobile Drawer, one-click persisted theme, and local Markdown overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("html")).toHaveAttribute("data-amadeus-color-scheme", "dark");
  await createConversation(page, "[markdown] 检查布局");
  await expect(page.getByRole("heading", { name: "Markdown 验证" })).toBeVisible();
  await page.getByRole("button", { name: "打开会话列表" }).click();
  const themeToggle = page.getByRole("button", { name: "切换为浅色主题" }).filter({ visible: true });
  await expect(themeToggle).toHaveText("");
  await themeToggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-amadeus-color-scheme", "light");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-amadeus-color-scheme", "light");
  await page.getByRole("button", { name: "打开会话列表" }).click();
  await expect(page.getByRole("button", { name: "切换为深色主题" }).filter({ visible: true })).toBeVisible();
  await expect(visibleButton(page, "新对话")).toBeVisible();
  const groupHeadingIds = await page.locator('section[aria-labelledby]').evaluateAll((sections) =>
    sections.map((section) => section.getAttribute("aria-labelledby")),
  );
  expect(new Set(groupHeadingIds).size).toBe(groupHeadingIds.length);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

async function createConversation(page: Page, message: string): Promise<void> {
  if (!(await visibleButton(page, "新对话").isVisible())) {
    await page.getByRole("button", { name: "打开会话列表" }).click();
  }
  const previousSession = new URL(page.url()).searchParams.get("session");
  await visibleButton(page, "新对话").click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("session"))
    .not.toBe(previousSession);
  await send(page, message);
}

async function send(page: Page, message: string): Promise<void> {
  await page.getByPlaceholder("给 Amadeus 发消息").fill(message);
  const sendButton = page.getByRole("button", { name: "发送消息" });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}

function visibleButton(page: Page, name: string) {
  return page.getByRole("button", { name, exact: true }).filter({ visible: true }).first();
}
