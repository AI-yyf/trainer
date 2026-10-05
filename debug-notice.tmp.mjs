import { spawn } from "node:child_process";
import process from "node:process";

const webviewDir = "/Users/Apple/Desktop/trainer/extension/webview";
const port = 56731;
const previewPath = "vscode-preview.html?view=coach&lang=en-US";

const child = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(port)], {
  cwd: webviewDir,
  env: { ...process.env, BROWSER: "none" },
  stdio: ["ignore", "pipe", "pipe"],
  detached: true,
});
child.stdout.setEncoding("utf8");
child.stderr.setEncoding("utf8");
let serverLog = "";
child.stdout.on("data", (c) => (serverLog += c));
child.stderr.on("data", (c) => (serverLog += c));

const url = `http://127.0.0.1:${port}/${previewPath}`;
let ready = false;
for (let i = 0; i < 120 && !ready; i++) {
  try {
    const res = await fetch(url);
    ready = res.ok;
  } catch {}
  if (!ready) await new Promise((r) => setTimeout(r, 250));
}
console.log("server ready:", ready);

const playwright = await import("playwright");
const browser = await playwright.chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE-ERROR:", m.text().slice(0, 300));
});

const dumpState = async (label) => {
  const info = await page.evaluate(() => {
    const banners = [...document.querySelectorAll("[data-template='SystemState']")].map((el) => ({
      scope: el.closest(".template-global-state") ? "global" : "inline",
      kind: el.getAttribute("data-system-state"),
      text: el.querySelector("h3")?.textContent?.trim() ?? el.textContent?.trim().slice(0, 80),
    }));
    return {
      banners,
      hasGlobalWrapper: Boolean(document.querySelector(".template-global-state")),
    };
  });
  console.log(label, JSON.stringify(info));
};

await page.goto(url, { waitUntil: "networkidle" });
await page.waitForFunction(() => typeof window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ === "function");
await page.waitForTimeout(250);

const inject = async (message) => {
  await page.evaluate((payload) => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__(payload), message);
  await page.waitForTimeout(300);
};

await dumpState("after-load:");
await inject({ type: "operation/status", payload: { tone: "success", message: "Provider settings saved." } });
await dumpState("after-op-status:");

const payload = await page.evaluate(() => {
  const p = structuredClone(window.__TRAINER_BOOTSTRAP__ ?? {});
  p.streamingState = {
    isStreaming: false,
    streamedContent: "Grounded answer.",
    streamMessageId: "msg-patch-complete",
    completionSummary: "Checked the workspace context first.",
    completionNextStep: "Apply the smallest verified patch.",
  };
  return p;
});
await inject({ type: "state/patch", payload });
await dumpState("after-state-patch:");

await browser.close();
try {
  process.kill(-child.pid, "SIGTERM");
} catch {
  child.kill("SIGTERM");
}
