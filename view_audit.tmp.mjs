import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/?live=1&sidecarPort=34901", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);

const focusReport = {};
for (const view of ["Chat", "Plan", "Resources", "Training", "Settings"]) {
  await page.getByRole("button", { name: view, exact: true }).first().click();
  await page.waitForTimeout(700);
  // Focus the view container then Tab several times, recording focused element info
  const seq = [];
  await page.evaluate(() => {
    const main = document.querySelector("main");
    if (main) main.setAttribute("tabindex", "-1");
    main?.focus();
  });
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    await page.waitForTimeout(120);
    const info = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return { tag: "(none)" };
      const style = getComputedStyle(el);
      return {
        tag: el.tagName,
        cls: (el.className || "").toString().slice(0, 40),
        text: (el.textContent || "").trim().slice(0, 24),
        outline: style.outlineStyle + "/" + style.outlineWidth,
        boxShadow: style.boxShadow !== "none",
      };
    });
    seq.push(info);
  }
  focusReport[view] = seq;
  await page.screenshot({ path: `/tmp/trainer_shots/r7-focus-${view.toLowerCase()}.png` });
}
console.log(JSON.stringify(focusReport, null, 1));
await browser.close();
