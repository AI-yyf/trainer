import { spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { chromium } from "playwright";

// Playwright Electron emulates focus in all instrumented renderers. Attach
// Chromium without its defaults so VS Code receives real window focus events.
export async function launchNativeFocusHost({ executablePath, args, env }) {
  const child = spawn(executablePath, ["--inspect=0", "--remote-debugging-port=0", ...args], {
    env, stdio: ["ignore", "pipe", "pipe"],
  });
  const lines = createInterface({ input: child.stderr });
  let browser;
  let inspector;
  try {
    const endpoints = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("VS Code debugging endpoints did not start.")), 90_000);
      const found = {};
      child.once("error", reject);
      child.once("exit", code => reject(new Error(`VS Code exited during focus setup (${code}).`)));
      lines.on("line", line => {
        const match = line.match(/^(Debugger|DevTools) listening on (ws:\/\/127\.0\.0\.1:\d+\/\S+)$/);
        if (!match) return;
        found[match[1]] = match[2];
        if (found.Debugger && found.DevTools) resolve(found);
      });
      child.once("exit", () => clearTimeout(timeout));
      lines.once("close", () => clearTimeout(timeout));
    });
    lines.close();
    inspector = new WebSocket(endpoints.Debugger);
    await once(inspector, "open");
    browser = await chromium.connectOverCDP(endpoints.DevTools, { noDefaults: true });
    const context = browser.contexts()[0];
    let sequence = 0;
    const evaluate = async expression => {
      const id = ++sequence;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => finish(new Error("VS Code main process did not respond.")), 10_000);
        function finish(error, value) {
          clearTimeout(timer);
          inspector.removeEventListener("message", receive);
          error ? reject(error) : resolve(value);
        }
        function receive(event) {
          const packet = JSON.parse(event.data);
          if (packet.id !== id) return;
          const failure = packet.error?.message ?? packet.result?.exceptionDetails?.text;
          finish(failure && new Error(failure), packet.result?.result?.value);
        }
        inspector.addEventListener("message", receive);
        inspector.send(JSON.stringify({ id, method: "Runtime.evaluate", params: {
          expression, returnByValue: true, includeCommandLineAPI: true,
        } }));
      });
    };
    return {
      process: () => child,
      firstWindow: options => context.pages()[0] ?? context.waitForEvent("page", options),
      nextWindow: options => context.waitForEvent("page", options),
      async focus(page) {
        const client = await context.newCDPSession(page);
        const { targetInfo } = await client.send("Target.getTargetInfo");
        await client.detach();
        return evaluate(`(() => {
          const { app, BrowserWindow, webContents } = require('electron');
          const contents = webContents.fromDevToolsTargetId(${JSON.stringify(targetInfo.targetId)});
          const window = BrowserWindow.fromWebContents(contents);
          app.focus({ steal: true });
          window.focus();
          contents.focus();
          return window.isFocused();
        })()`);
      },
      async close() {
        await evaluate("require('electron').app.quit() && true").catch(() => {});
        inspector.close();
        await browser.close();
        if (child.exitCode === null) child.kill();
      },
    };
  } catch (error) {
    lines.close();
    inspector?.close();
    await browser?.close();
    child.kill();
    throw error;
  }
}
