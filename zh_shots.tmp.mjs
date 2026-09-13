import { chromium } from "playwright";
import fs from "node:fs";
fs.mkdirSync("/tmp/trainer_func/zh", { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/?live=1&sidecarPort=34901", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
await page.getByRole("button", { name: "Settings", exact: true }).first().click();
await page.waitForTimeout(800);
await page.evaluate(() => {
  const pills = [...document.querySelectorAll("button.settings-sheet__choice-pill")];
  const zh = pills.find(b => (b.textContent || "").trim() === "简体中文");
  zh?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
});
await page.waitForTimeout(1500);
await page.screenshot({ path: "/tmp/trainer_func/zh/settings.png" });
console.log("settings zh done, active lang pill check");
const views = ["对话", "计划", "资料", "训练"];
for (const v of views) {
  await page.getByRole("button", { name: v, exact: true }).first().click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `/tmp/trainer_func/zh/${v}.png` });
  console.log("shot:", v);
}
await browser.close();
