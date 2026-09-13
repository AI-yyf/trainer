import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/?live=1&sidecarPort=34901", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
await page.getByRole("button", { name: "Settings", exact: true }).first().click();
await page.waitForTimeout(800);
const found = await page.evaluate(() => {
  const candidates = [...document.querySelectorAll("button, [role='button'], [class*='presence'], [class*='choice']")];
  return candidates
    .filter(b => /english|language/i.test(b.textContent || ""))
    .map(b => ({ text: (b.textContent || "").trim().slice(0, 60), cls: (b.className || "").toString().slice(0, 60), aria: b.getAttribute("aria-label") }));
});
console.log(JSON.stringify(found, null, 1));
await browser.close();
