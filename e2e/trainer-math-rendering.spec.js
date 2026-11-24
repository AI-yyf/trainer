const { test, expect } = require("playwright/test");

/**
 * Coach replies carry mathematics, rendered by KaTeX through remark-math and
 * rehype-katex (plus its mhchem extension for chemistry). These cases render
 * real formulas in a real browser, which is the only way to notice a math
 * library update that still type-checks but draws differently — or not at all.
 */

async function showReply(page, body) {
  await page.goto("/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=math");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate((body) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "bootstrap",
      payload: {
        ...current,
        sessionHistoryRestored: true,
        conversation: [{ id: "math-reply", role: "assistant", author: "Trainer", timestamp: "10:00", body }],
      },
    });
  }, body);
}

const REPLY = [
  "Spaced repetition keeps the review count at $O(\\log n)$ per item.",
  "",
  "$$",
  "\\int_0^1 x^2 \\, dx = \\frac{1}{3}",
  "$$",
  "",
  "Water is $\\ce{H2O}$.",
].join("\n");

test("inline and display mathematics render as typeset formulas", async ({ page }) => {
  await showReply(page, REPLY);

  // Two inline formulas and one display formula.
  const formulas = page.locator(".message-bubble .katex");
  await expect(formulas).toHaveCount(3);
  // Each one has a visual layer and the original TeX for assistive technology.
  const first = formulas.first();
  await expect(first.locator(".katex-html")).toHaveCount(1);
  await expect(first.locator("annotation")).toContainText("O(\\log n)");

  const display = page.locator(".message-bubble .katex-display");
  await expect(display).toHaveCount(1);
  const text = await display.textContent();
  expect(text).toContain("∫");
  expect(text).toContain("dx");
  // The glyphs are laid out with real extent, not collapsed to a line of text.
  const box = await display.boundingBox();
  expect(box.height).toBeGreaterThan(24);

  // The stylesheet shipped with the math library is what spaces its glyphs.
  const fontFaceLoaded = await page.evaluate(() =>
    Array.from(document.fonts).some((font) => /KaTeX/i.test(font.family)),
  );
  expect(fontFaceLoaded).toBe(true);
});

test("an unsupported command stays visible as text instead of disappearing", async ({ page }) => {
  // The renderer does not throw on unknown TeX: the command is drawn in the
  // error colour, in place, so the learner sees that something did not render
  // rather than a silent gap.
  await showReply(page, "Broken: $\\thisCommandDoesNotExist{x}$.");

  const formula = page.locator(".message-bubble .katex");
  await expect(formula).toHaveCount(1);
  await expect(formula.locator(".katex-html")).toContainText("\\thisCommandDoesNotExist");
  // The argument after it still typesets.
  await expect(formula.locator(".katex-html")).toContainText("x");
  // Nothing escaped into the page as raw markup.
  expect(await page.locator(".message-bubble").innerHTML()).not.toContain("<script");
});

test("chemistry formulas typeset through the mhchem extension", async ({ page }) => {
  await showReply(page, REPLY);

  // mhchem turns `H2O` into an H, a subscripted 2 and an O. Without the
  // extension the command would be drawn as unknown TeX and no subscript
  // would exist.
  const chemistry = page.locator(".message-bubble .katex").filter({ has: page.locator("annotation", { hasText: "\\ce{H2O}" }) });
  await expect(chemistry).toHaveCount(1);
  await expect(chemistry.locator("msub")).toHaveCount(1);
  await expect(chemistry.locator("msub")).toContainText("2");
  await expect(page.locator(".message-bubble .katex-error")).toHaveCount(0);
});
