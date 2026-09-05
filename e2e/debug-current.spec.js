const { test } = require("playwright/test");

test("debug current browser preview actions", async ({ page }) => {
  const logs = [];
  page.on("console", async (message) => {
    if (message.type() === "log") console.log("PAGE_LOG", message.text());
    if (message.type() === "debug") {
      logs.push({ text: message.text(), values: await Promise.all(message.args().map((arg) => arg.jsonValue().catch(() => "<unreadable>"))) });
    }
  });
  page.on("request", request => {
    if (request.url().includes("/provider/") || request.url().includes("/evidence")) {
      console.log("REQ", request.method(), request.url(), request.postData() || "");
    }
  });
  page.on("response", response => {
    if (response.url().includes("/provider/") || response.url().includes("/evidence")) {
      console.log("RESP", response.status(), response.url());
    }
  });
  await page.goto("/vscode-preview.html?view=plan&lang=en-US&scenario=plan-blocked&connection=connected");
  await page.waitForLoadState("networkidle");
  console.log("ENV", await page.evaluate(() => ({ api: typeof window.acquireVsCodeApi, preview: window.__TRAINER_BROWSER_PREVIEW__, storage: window.__TRAINER_PREVIEW_STORAGE_KEY__ })));
  await page.evaluate(() => {
    document.addEventListener("click", event => console.log("DOM_CLICK", event.target?.closest?.("button")?.textContent || "none"), true);
    window.addEventListener("trainer:webview-action", event => console.log("ACTION_EVENT", JSON.stringify(event.detail)));
  });
  await page.getByText("More", { exact: true }).click();
  const evidence = page.locator(".coach-plan-view__details-group--evidence");
  const adoptButton = evidence.getByRole("button", { name: "Adopt", exact: true }).first();
  console.log("BUTTON", await adoptButton.evaluate((el) => { const rect = el.getBoundingClientRect(); const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2); return { disabled: el.disabled, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, hit: hit?.outerHTML?.slice(0, 160), html: el.outerHTML.slice(0, 300) }; }));
  await adoptButton.dispatchEvent("click");
  await page.waitForTimeout(1000);
  console.log("LOGS", JSON.stringify(logs));
  console.log("ACTION_API", await page.evaluate(() => { window.acquireVsCodeApi?.().postMessage({ type: "command/execute", payload: { commandId: "trainer.evidence.adopt", payload: { evidenceId: "evidence-plan-1" } } }); return true; }));
  await page.waitForTimeout(500);
  console.log("LOGS_AFTER_MANUAL", JSON.stringify(logs));
  console.log("NOTICES", await page.locator(".notice").allTextContents());
  console.log("ADOPT_COUNT", await evidence.getByRole("button", { name: "Adopt", exact: true }).count());
});

test("debug live provider save", async ({ page }) => {
  await page.route("**/session/start", async route => route.fulfill({ contentType: "application/json", body: JSON.stringify({ session_id: "debug-session" }) }));
  await page.route("**/memory/summary**", async route => route.fulfill({ contentType: "application/json", body: JSON.stringify({}) }));
  await page.route("**/provider/test", async route => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, status: "connected" }) }));
  page.on("console", async message => {
    console.log("CONSOLE", message.type(), message.text());
    if (message.text().includes("debug-provider-profile-save")) {
      console.log("CONSOLE_ARGS", JSON.stringify(await Promise.all(message.args().map(arg => arg.jsonValue().catch(() => "<unreadable>")))));
    }
  });
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=debug&live=1");
  await page.waitForLoadState("networkidle");
  console.log("LIVE_ENV", await page.evaluate(() => ({ hook: typeof window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__, api: typeof window.acquireVsCodeApi, body: document.body.innerText.slice(0, 120) })));
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({ type: "operation/status", payload: { tone: "success", message: "Synthetic success" } }));
  await page.waitForTimeout(100);
  console.log("SYNTHETIC", await page.locator(".notice").allTextContents());
  await page.evaluate(() => {
    const deliver = window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__;
    if (deliver) window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ = (message) => { console.log("HOST_MSG", JSON.stringify(message)); deliver(message); };
    const originalFetch = window.fetch;
    window.fetch = (...args) => { console.log("FETCH", String(args[0])); return originalFetch(...args); };
  });
  const detail = page.locator(".coach-settings-view__provider-detail");
  if (!(await detail.evaluate(element => element.open))) await detail.locator(":scope > summary").click();
  const fields = detail.locator("details.settings-sheet__minor-panel").filter({ hasText: "Connection fields and key" });
  if (!(await fields.evaluate(element => element.open))) await fields.locator(":scope > summary").click();
  await fields.getByLabel("Connection name (optional)", { exact: true }).fill("Debug provider");
  await fields.getByLabel("Service root").fill("https://provider.invalid/v1");
  await fields.getByLabel("API Key", { exact: true }).fill("debug-key");
  const picker = fields.locator("details.settings-model-picker");
  if (!(await picker.evaluate(element => element.open))) await picker.locator(":scope > summary").click();
  const manual = picker.getByRole("button", { name: "Enter a full model name", exact: true });
  if (await manual.count()) await manual.click();
  const search = picker.getByRole("searchbox", { name: "Filter models", exact: true });
  await search.fill("debug-model");
  await picker.getByRole("button", { name: "Use debug-model", exact: true }).click();
  const profiles = page.locator(".settings-sheet__provider-profiles");
  if (!(await profiles.evaluate(element => element.open))) await profiles.locator(":scope > summary").click();
  const saveProfile = profiles.getByRole("button", { name: "Save as connection", exact: true });
  console.log("SAVE_PROFILE", await saveProfile.evaluate((element) => ({ disabled: element.disabled, html: element.outerHTML.slice(0, 220) })));
  await saveProfile.click();
  await page.waitForTimeout(500);
  console.log("PROFILE_AFTER", await profiles.innerText());
  await page.waitForTimeout(1000);
  console.log("LIVE_NOTICES", await page.locator(".notice").allTextContents());
  console.log("LIVE_STATUS", await page.locator(".settings-availability-strip").allTextContents());
});
