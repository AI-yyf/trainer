const { test, expect } = require("playwright/test");

/**
 * An image that lives on another site reports the learner's reading to that
 * site. Model output and imported documents are not trusted with that, so a
 * remote image is held back until the learner clicks it
 * (webview/src/lib/remoteImages.ts).
 *
 * These cases watch the network, which is the only honest way to prove that
 * nothing loads on its own.
 */

const TRACKER = "https://img-tracker.invalid";
// A 1x1 transparent PNG, so a loaded image is a real one.
const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);
const INLINE_PNG = `data:image/png;base64,${PIXEL.toString("base64")}`;

async function showReply(page, body, lang = "en-US") {
  await page.goto(`/vscode-preview.html?view=coach&lang=${lang}&connection=connected&run=remote-images`);
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate((body) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "bootstrap",
      payload: {
        ...current,
        sessionHistoryRestored: true,
        conversation: [{ id: "image-reply", role: "assistant", author: "Trainer", timestamp: "10:00", body }],
      },
    });
  }, body);
}

test("a remote image in a coach reply loads only when the learner clicks it", async ({ page }) => {
  const requests = [];
  await page.route(`${TRACKER}/**`, (route) => {
    requests.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "image/png", body: PIXEL });
  });

  await showReply(
    page,
    `Here is the architecture:\n\n![System architecture](${TRACKER}/fig.png?topic=fsrs)\n\nAnd an inline one:\n\n![inline](${INLINE_PNG})`,
  );

  // The remote image is a placeholder that says where it would come from.
  const placeholder = page.locator('[data-rich-image="remote"] .trainer-remote-image');
  await expect(placeholder).toBeVisible();
  await expect(placeholder).toContainText("Load remote image");
  await expect(placeholder).toContainText("img-tracker.invalid");
  await expect(placeholder).toContainText("System architecture");
  await expect(placeholder).toHaveAttribute(
    "title",
    /Remote images stay unloaded until you click/,
  );

  // A local image is not held back: it is the learner's own content.
  const inline = page.locator('[data-rich-image="true"] img');
  await expect(inline).toHaveCount(1);
  await expect(inline).toHaveAttribute("src", /^data:image\/png;base64,/);

  // Nothing was fetched from the other site — not while rendering, not after
  // the page settled.
  await page.waitForTimeout(700);
  expect(requests).toEqual([]);
  expect(await page.locator(`img[src^="${TRACKER}"]`).count()).toBe(0);

  // One click, one image, exactly that image.
  await placeholder.click();
  const loaded = page.locator(`img[src="${TRACKER}/fig.png?topic=fsrs"]`);
  await expect(loaded).toBeVisible();
  await expect(loaded).toHaveAttribute("alt", "System architecture");
  expect(requests).toEqual([`${TRACKER}/fig.png?topic=fsrs`]);
  await expect(page.locator('[data-rich-image="remote"]')).toHaveCount(0);
});

test("an svg paint-server URL in model HTML never fetches on its own", async ({ page }) => {
  const requests = [];
  await page.route(`${TRACKER}/**`, (route) => {
    requests.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg/>" });
  });

  await showReply(
    page,
    `<svg width="80" height="20"><rect width="80" height="20" ` +
      `fill="url(${TRACKER}/paint.svg#g)" /></svg>`,
  );
  await page.waitForTimeout(700);

  // A CSS paint server is fetched by the browser on render, without a click;
  // the sanitizer keeps only same-document fragment references. Raw markup
  // may also be rendered as escaped text — that is inert; what must not exist
  // is a live SVG attribute pointing at the tracker.
  expect(requests).toEqual([]);
  expect(
    await page.locator('[fill*="url("], [stroke*="url("], [filter*="url("]').count(),
  ).toBe(0);
});

test("the placeholder is written in the learner's language", async ({ page }) => {
  await page.route(`${TRACKER}/**`, (route) => route.abort());
  await showReply(page, `![架构](${TRACKER}/fig.png)`, "zh-CN");

  const placeholder = page.locator('[data-rich-image="remote"] .trainer-remote-image');
  await expect(placeholder).toContainText("加载远程图片");
  await expect(placeholder).toHaveAttribute("title", /远程图片在你点击之前不会加载/);
});

test("a remote image inside a sanitized HTML preview also waits for a click", async ({ page }) => {
  // The app installs one delegated listener for every sanitized preview.
  // This is the markup the sanitizer leaves in place of a remote image.
  const requests = [];
  await page.route(`${TRACKER}/**`, (route) => {
    requests.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "image/png", body: PIXEL });
  });
  await showReply(page, "Opening the document…");
  await page.evaluate((tracker) => {
    const preview = document.createElement("div");
    preview.id = "sanitized-preview-probe";
    preview.innerHTML =
      `<p>Document text <span id="probe-emphasis">emphasis</span></p>` +
      `<button type="button" class="trainer-remote-image" data-trainer-remote-image="true" ` +
      `data-remote-src="${tracker}/doc.png" data-remote-alt="Figure 1" data-remote-width="200" title="hint">` +
      `<span class="trainer-remote-image__label">Load remote image</span></button>` +
      `<button type="button" class="trainer-remote-image" data-trainer-remote-image="true" ` +
      `data-remote-src="${tracker}/second.png"><span class="trainer-remote-image__label">Load remote image</span></button>`;
    document.querySelector(".coach-conversation-view__list").appendChild(preview);
  }, TRACKER);

  const preview = page.locator("#sanitized-preview-probe");
  await expect(preview).toBeVisible();
  await page.waitForTimeout(500);
  expect(requests).toEqual([]);

  // Clicking the document's own text, deep inside an element, loads nothing.
  await preview.locator("p").click({ position: { x: 2, y: 2 } });
  await preview.locator("#probe-emphasis").click();
  await page.waitForTimeout(300);
  expect(requests).toEqual([]);

  await preview.locator(".trainer-remote-image").first().click();
  await expect(preview.locator(`img[src="${TRACKER}/doc.png"]`)).toBeVisible();
  await expect(preview.locator(`img[src="${TRACKER}/doc.png"]`)).toHaveAttribute("alt", "Figure 1");
  await expect(preview.locator(`img[src="${TRACKER}/doc.png"]`)).toHaveAttribute("width", "200");
  expect(requests).toEqual([`${TRACKER}/doc.png`]);
  await expect(preview.locator(".trainer-remote-image")).toHaveCount(1);

  // A placeholder rewritten to something that is not a remote image stays inert.
  await preview.evaluate((node) => {
    node.querySelector(".trainer-remote-image").setAttribute("data-remote-src", "javascript:alert(1)");
  });
  await preview.locator(".trainer-remote-image").click();
  await expect(preview.locator(".trainer-remote-image")).toHaveCount(1);
  expect(requests).toEqual([`${TRACKER}/doc.png`]);
});
