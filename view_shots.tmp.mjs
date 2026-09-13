import { chromium } from "playwright";
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
// 滚到设置底部并截图
await page.evaluate(() => {
  const pane = document.querySelector(".settings-pane") || document.querySelector("main");
  pane.scrollTop = pane.scrollHeight;
});
await page.waitForTimeout(600);
await page.screenshot({ path: "/tmp/trainer_func/r1-settings-bottom.png" });
const stats = await page.evaluate(() => {
  const pane = document.querySelector(".settings-pane");
  return {
    paneScrollHeight: pane?.scrollHeight ?? 0,
    paneClientHeight: pane?.clientHeight ?? 0,
    sections: pane ? pane.querySelectorAll("section").length : 0,
    details: pane ? pane.querySelectorAll("details").length : 0,
    detailsOpen: pane ? pane.querySelectorAll("details[open]").length : 0,
    collapseSections: pane ? pane.querySelectorAll(".collapse-section").length : 0,
    buttons: pane ? pane.querySelectorAll("button").length : 0,
  };
});
console.log("stats:", JSON.stringify(stats));
await browser.close();
