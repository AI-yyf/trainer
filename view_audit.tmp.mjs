import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/?live=1&sidecarPort=34901", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
const views = ["Chat", "Plan", "Resources", "Training", "Settings"];
for (const view of views) {
  await page.getByRole("button", { name: view, exact: true }).first().click();
  await page.waitForTimeout(900);
  await page.screenshot({ path: `/tmp/trainer_shots/final-${view.toLowerCase()}.png` });
}
console.log("final grid captured");
await browser.close();
