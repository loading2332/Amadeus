import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/static/");
  await expect(page.getByText("Amadeus", { exact: true }).first()).toBeVisible();
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
  await page.getByRole("button", { name: /\[slow\] 会话甲/ }).click();
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
  await expect(page.getByText("失败前的部分回答")).toBeVisible();
  await expect(page.getByText(/失败/).last()).toBeVisible();
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("确定性回答")).toBeVisible();
  await expect(page.getByText("失败前的部分回答")).toBeVisible();
});

test("supports mobile Drawer, persisted theme, and local Markdown overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await createConversation(page, "[markdown] 检查布局");
  await expect(page.getByRole("heading", { name: "Markdown 验证" })).toBeVisible();
  await page.getByRole("button", { name: "打开会话列表" }).click();
  await page.getByRole("combobox", { name: "主题" }).filter({ visible: true }).click();
  await page.getByRole("option", { name: "深色" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-amadeus-color-scheme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-amadeus-color-scheme", "dark");
  await page.getByRole("button", { name: "打开会话列表" }).click();
  await expect(visibleButton(page, "新对话")).toBeVisible();
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
