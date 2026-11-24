const { test, expect } = require("playwright/test");

/**
 * A Mermaid diagram in a coach reply is model output turned into markup.
 *
 * These cases render real diagrams in a real browser and check the three
 * fences around them (webview/src/lib/mermaidDiagram.ts):
 *
 *   1. a normal diagram still draws, with its theme;
 *   2. nothing executable or resource-loading gets through;
 *   3. a diagram cannot restyle the workbench around it — its stylesheet
 *      lives in a closed shadow root that only reaches the diagram.
 *
 * The hostile chart uses Mermaid's own directive to plant page-wide CSS,
 * an image with an event handler in a label, and a script link.
 */

const BENIGN_CHART = ["flowchart LR", "  A[Decide & act] -->|yes| B((Do it))", "  B --> C[Review]"].join("\n");

const HOSTILE_CSS = [
  ".message-mermaid { display: none !important; }",
  "body { background: rgb(255, 0, 0) !important; }",
  ".leak { background: url(https://mermaid-tracker.invalid/pixel.png); }",
].join(" ");

const HOSTILE_CHART = [
  `%%{init: {"themeCSS": ${JSON.stringify(HOSTILE_CSS)}}}%%`,
  "flowchart LR",
  `  A["<img src=x onerror='window.__mermaidPwned = 1'>label"] --> B[End]`,
  `  click B "javascript:window.__mermaidPwned = 2" "tooltip"`,
].join("\n");

async function showReply(page, body, run) {
  await page.goto(`/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=${run}`);
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate((body) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "bootstrap",
      payload: {
        ...current,
        sessionHistoryRestored: true,
        conversation: [{ id: "diagram-reply", role: "assistant", author: "Trainer", timestamp: "10:00", body }],
      },
    });
  }, body);
}

/** Facts about the first diagram host that can be observed from outside it. */
async function diagramHostFacts(page) {
  return page.evaluate(() => {
    const host = document.querySelector('[data-mermaid-host="true"]');
    if (!host) {
      return null;
    }
    const rect = host.getBoundingClientRect();
    return {
      rendered: host.dataset.rendered === "true",
      // A closed shadow root is exactly what keeps page scripts out.
      closed: host.shadowRoot === null,
      lightChildren: host.childNodes.length,
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  });
}

test("a normal diagram draws inside its own closed shadow root", async ({ page }) => {
  await showReply(page, `Here is the flow:\n\n\`\`\`mermaid\n${BENIGN_CHART}\n\`\`\``);

  await expect(page.locator('[data-mermaid-host="true"][data-rendered="true"]')).toHaveCount(1);
  await expect(page.locator(".message-mermaid--error")).toHaveCount(0);

  const facts = await diagramHostFacts(page);
  expect(facts.rendered).toBe(true);
  expect(facts.closed).toBe(true);
  expect(facts.lightChildren).toBe(0);
  // Three nodes and two edges: a picture with real extent, not an empty box.
  expect(facts.height).toBeGreaterThan(40);
  expect(facts.width).toBeGreaterThan(120);
  // The scroll container around the diagram kept its own size cap.
  const canvas = await page.locator(".message-mermaid__canvas").evaluate((node) => getComputedStyle(node).maxHeight);
  expect(canvas).toBe("320px");
});

test("a hostile diagram cannot run script, load a resource or restyle the workbench", async ({ page }) => {
  const trackerRequests = [];
  await page.route("**/mermaid-tracker.invalid/**", (route) => {
    trackerRequests.push(route.request().url());
    return route.abort();
  });

  await showReply(page, `Look at this:\n\n\`\`\`mermaid\n${HOSTILE_CHART}\n\`\`\``);
  await expect(page.locator('[data-mermaid-host="true"][data-rendered="true"]')).toHaveCount(1);

  // Nothing from the diagram reached the light DOM.
  const injected = await page.evaluate(() => {
    const block = document.querySelector(".message-mermaid");
    return {
      script: block.querySelectorAll("script").length,
      images: block.querySelectorAll("img, image, iframe").length,
      links: block.querySelectorAll("a").length,
      handlers: Array.from(block.querySelectorAll("*")).filter((node) =>
        Array.from(node.attributes).some((attribute) => attribute.name.toLowerCase().startsWith("on")),
      ).length,
      pwned: String(window.__mermaidPwned),
      // The diagram's stylesheet tried to hide its own container and paint
      // the page: neither may have happened.
      blockDisplay: getComputedStyle(block).display,
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      blockHeight: Math.round(block.getBoundingClientRect().height),
      composerMounted: Boolean(document.querySelector(".composer__body")),
    };
  });
  expect(injected.script).toBe(0);
  expect(injected.images).toBe(0);
  expect(injected.links).toBe(0);
  expect(injected.handlers).toBe(0);

  // Clicking where the diagram's node and link were must not run anything.
  const host = page.locator('[data-mermaid-host="true"]');
  const box = await host.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(200);
  expect(await page.evaluate(() => String(window.__mermaidPwned))).toBe("undefined");

  expect(injected.blockDisplay).not.toBe("none");
  expect(injected.blockHeight).toBeGreaterThan(40);
  expect(injected.bodyBackground).not.toBe("rgb(255, 0, 0)");
  // The composer is still there and still the one place to type.
  expect(injected.composerMounted).toBe(true);
  await expect(page.locator("textarea").first()).toBeVisible();
  await expect(page.locator("textarea")).toHaveCount(1);
  expect(trackerRequests).toEqual([]);
});

test("a diagram too large to render safely is shown as its source", async ({ page }) => {
  const oversized = ["flowchart TD"].concat(
    Array.from({ length: 400 }, (_, index) => `  N${index} --> N${index + 1}`),
  ).join("\n");
  await showReply(page, `\`\`\`mermaid\n${oversized}\n\`\`\``, "oversized");

  await expect(page.locator('[data-mermaid-host="true"]')).toHaveCount(0);
  const failed = page.locator(".message-mermaid--error");
  await expect(failed).toBeVisible();
  // The learner still gets the chart, as text.
  await expect(failed.locator("pre").first()).toContainText("N399 --> N400");
});

test("a label image never loads while Mermaid is still rendering", async ({ page }) => {
  // Mermaid mounts its working SVG in the page before the scrubber runs, so
  // a label's own HTML is live at that moment. DOMPurify's defaults keep
  // `<img>`, which turned one label into a request to a third-party host.
  const labelRequests = [];
  await page.route("**/mermaid-tracker.invalid/**", (route) => {
    labelRequests.push(route.request().url());
    return route.abort();
  });
  await showReply(
    page,
    [
      "Diagram:",
      "",
      "```mermaid",
      "flowchart LR",
      '  A["<img src=https://mermaid-tracker.invalid/label.png>label"] --> B[End]',
      "```",
      "",
    ].join("\n"),
    "label-image",
  );

  await expect(page.locator('[data-mermaid-host="true"][data-rendered="true"]')).toHaveCount(1);
  expect(labelRequests.filter((url) => url.includes("/label.png"))).toEqual([]);
  // The invisible container rendering happens in is gone afterwards.
  const containers = await page.evaluate(
    () => document.querySelectorAll('body > div[aria-hidden="true"]').length,
  );
  expect(containers).toBe(0);
});

test("a diagram that does not parse leaves nothing of Mermaid behind", async ({ page }) => {
  await showReply(
    page,
    ["Broken:", "", "```mermaid", "flowchart LR", "  A[unclosed --> (((", "```", ""].join("\n"),
    "unparsable",
  );

  await expect(page.locator(".message-mermaid--error")).toHaveCount(1);
  const leftovers = await page.evaluate(() => ({
    temporary: document.querySelectorAll('[id^="dtrainer-mermaid-"]').length,
    syntaxErrorSvg: Array.from(document.querySelectorAll("svg")).filter((svg) =>
      (svg.textContent || "").includes("Syntax error"),
    ).length,
    containers: document.querySelectorAll('body > div[aria-hidden="true"]').length,
  }));
  expect(leftovers).toEqual({ temporary: 0, syntaxErrorSvg: 0, containers: 0 });
});
