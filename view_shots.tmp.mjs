import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/?live=1&sidecarPort=34901", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
// 切换语言到简体中文:设置里找语言选择器
await page.getByRole("button", { name: "Settings", exact: true }).first().click();
await page.waitForTimeout(800);
const langSel = await page.evaluate(() => {
  const selects = [...document.querySelectorAll("select")];
  for (const s of selects) {
    const opt = [...s.options].find(o => /简体中文|zh-CN/.test(o.textContent || ""));
    if (opt) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;
      setter.call(s, opt.value);
      s.dispatchEvent(new Event("change", { bubbles: true }));
      return { found: true, value: opt.value };
    }
  }
  return { found: false };
});
console.log("lang switch:", JSON.stringify(langSel));
await page.waitForTimeout(1200);
await page.screenshot({ path: "/tmp/trainer_func/zh-settings.png" });
const views = ["对话", "计划", "资料", "训练"];
await page.getByRole("button", { name: "对话", exact: true }).first().click().catch(async () => {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find(x => x.textContent.trim() === "对话");
    b?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
});
await page.waitForTimeout(900);
await page.screenshot({ path: "/tmp/trainer_func/zh-chat.png" });
console.log("zh shots done");
await browser.close();
