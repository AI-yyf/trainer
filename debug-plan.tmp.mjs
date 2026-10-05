import { spawn } from "node:child_process";
import process from "node:process";

const webviewDir = "/Users/Apple/Desktop/trainer/extension/webview";
const port = 56735;
const previewPath = "vscode-preview.html?view=plan&lang=en-US&scenario=ready";

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
if (!ready) console.log("SERVER LOG:", serverLog.slice(-400));

const playwright = await import("playwright");
const browser = await playwright.chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 300, height: 800 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));

await page.goto(url, { waitUntil: "networkidle" });
await page.waitForSelector('[data-plan-primary="true"]', { timeout: 30000 });
await page.waitForTimeout(400);

const info = await page.evaluate(() => {
  const primary = document.querySelector('[data-plan-primary="true"]');
  const out = [];
  const dump = (el, depth) => {
    if (!el || depth > 6 || out.length > 60) return;
    const tag = el.tagName.toLowerCase();
    const cls = typeof el.className === "string" && el.className ? "." + el.className.trim().split(/\s+/).join(".") : "";
    const data = [...el.attributes].filter((a) => a.name.startsWith("data-")).map((a) => `[${a.name}=${a.value}]`).join("");
    const ownText = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).filter(Boolean).join(" ");
    const rect = el.getBoundingClientRect();
    const vis = rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
    out.push(`${"  ".repeat(depth)}${tag}${cls}${data} vis=${vis}${ownText ? " :: " + ownText.slice(0, 100) : ""}`);
    for (const c of el.children) dump(c, depth + 1);
  };
  dump(primary, 0);
  const fact = primary?.querySelector('[data-plan-fact="next"]');
  const btn = primary?.querySelector('[data-primary-action="true"]');
  return {
    tree: out.join("\n"),
    factInfo: fact ? {
      text: fact.textContent.replace(/\s+/g, " ").trim(),
      clipped: fact.scrollHeight > fact.clientHeight + 1,
      rect: fact.getBoundingClientRect().toJSON(),
    } : null,
    btnInfo: btn ? {
      text: btn.textContent.trim(),
      disabled: btn.hasAttribute("disabled"),
      rect: btn.getBoundingClientRect().toJSON(),
    } : null,
  };
});
console.log(info.tree);
console.log("FACT:", JSON.stringify(info.factInfo));
console.log("BTN:", JSON.stringify(info.btnInfo));

await browser.close();
try {
  process.kill(-child.pid, "SIGTERM");
} catch {
  child.kill("SIGTERM");
}
