import { spawn } from "node:child_process";
import process from "node:process";

const webviewDir = "/Users/Apple/Desktop/trainer/extension/webview";
const port = 56733;
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
if (!ready) console.log("SERVER LOG:", serverLog.slice(-500));

const playwright = await import("playwright");
const browser = await playwright.chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));

await page.goto(url, { waitUntil: "networkidle" });
await page.waitForFunction(() => typeof window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ === "function");
await page.waitForTimeout(250);

await page.evaluate((payload) => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__(payload), {
  type: "ui/restoreView",
  payload: {
    activeView: "practice",
    trainingSubmode: "practice",
    trainingRestoreTarget: "next_hop",
    focusArea: "provider truth",
    currentStageTitle: "Verification",
    latestSummary: "Carry the verified result back to coach.",
    latestTrainingNextHop: {
      cardTitle: "Return to provider truth",
      summary: "Re-open the smallest provider check before widening scope.",
      continueIn: "training",
      status: "surfaced",
      targetId: "card-provider-truth",
    },
  },
});
await page.waitForSelector(".training-pane", { timeout: 30000 });
await page.waitForTimeout(400);

const info = await page.evaluate(() => {
  const pane = document.querySelector(".training-pane");
  const dump = (el, depth, out) => {
    if (!el || depth > 8 || out.length > 120) return;
    const tag = el.tagName.toLowerCase();
    const cls = typeof el.className === "string" && el.className ? "." + el.className.trim().split(/\s+/).join(".") : "";
    const data = [...el.attributes].filter((a) => a.name.startsWith("data-")).map((a) => `[${a.name}=${a.value}]`).join("");
    const ownText = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).filter(Boolean).join(" ");
    out.push(`${"  ".repeat(depth)}${tag}${cls}${data}${ownText ? " :: " + ownText.slice(0, 90) : ""}`);
    for (const child of el.children) dump(child, depth + 1, out);
  };
  const out = [];
  dump(pane, 0, out);
  return out.join("\n");
});
console.log(info);

await browser.close();
try {
  process.kill(-child.pid, "SIGTERM");
} catch {
  child.kill("SIGTERM");
}
