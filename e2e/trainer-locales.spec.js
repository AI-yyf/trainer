/**
 * Narrow-sidebar locale acceptance for the standalone Trainer Preview.
 * Run: npx playwright test e2e/trainer-locales.spec.js
 */

const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";
const VIEWPORT_WIDTHS = [300, 360, 420];
const TRAINING_CARD_FACTS = ["deliverable", "verify"];
const PROGRESS_LABELS = { "es-ES": "Progreso", "fr-FR": "Progrès", "de-DE": "Fortschritt",
  "ja-JP": "成長", "ko-KR": "성장", "pt-BR": "Progresso" };

const VIEW_LABELS = {
  "es-ES": ["Chat", "Plan", "Recursos", "Entrenamiento", "Ajustes"],
  "fr-FR": ["Chat", "Plan", "Ressources", "Entra\u00eenement", "Param\u00e8tres"],
  "de-DE": ["Chat", "Plan", "Materialien", "Training", "Einstellungen"],
  "ja-JP": [
    "\u5bfe\u8a71",
    "\u8a08\u753b",
    "\u8cc7\u6599",
    "\u8a13\u7df4",
    "\u8a2d\u5b9a",
  ],
  "ko-KR": [
    "\ub300\ud654",
    "\uacc4\ud68d",
    "\uc790\ub8cc",
    "\ud6c8\ub828",
    "\uc124\uc815",
  ],
  "pt-BR": ["Chat", "Plano", "Recursos", "Treinamento", "Configura\u00e7\u00f5es"],
};

function buildPreviewUrl(language) {
  const params = new URLSearchParams({
    view: "training",
    lang: language,
    scenario: "training-remote",
    connection: "connected",
  });
  return `${PREVIEW_PATH}?${params.toString()}`;
}

async function openStandaloneTrainingPreview(page, language, width) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(buildPreviewUrl(language));
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-template=FocusedPractice]')).toBeVisible();
}

async function expectThreeLocalizedPrimaryDestinations(page, language) {
  const tabs = page.locator(".app-shell-nav button");
  await expect(tabs).toHaveCount(3);
  expect(await tabs.evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-label")))).toEqual(VIEW_LABELS[language].slice(0, 3));
  await expect(tabs.nth(1)).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("trainer-view-nav-settings")).toHaveAttribute("aria-label", VIEW_LABELS[language][4]);
}
async function expectCurrentTrainingCardFacts(page) {
  const card = page.locator('[data-template=FocusedPractice]');
  await expect(card.locator('.template-activity-header h2')).toContainText(/\S/);
  await expect(card.locator('.template-activity-header .template-metadata')).toContainText(/[1-5]\/5/);
  expect(await card.locator('[data-primary-action="true"]:visible').count()).toBeLessThanOrEqual(1);
  await expect(page.locator('.composer-shell')).toHaveCount(0);
  const details = card.locator('details');
  for (let i = 0; i < await details.count(); i++) await expect(details.nth(i)).not.toHaveAttribute("open", "");
}

async function expectNoHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => ({
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    rootClientWidth: document.documentElement.clientWidth,
    rootScrollWidth: document.documentElement.scrollWidth,
  }));

  expect(metrics.bodyScrollWidth).toBeLessThanOrEqual(metrics.bodyClientWidth + 1);
  expect(metrics.rootScrollWidth).toBeLessThanOrEqual(metrics.rootClientWidth + 1);
}

async function expectSpanishNextHopIsLocalized(page) {
  const training = page.locator(".training-pane--card-only");
  await expect(training.locator(".template-activity-header h2")).toBeVisible();
  await expect(training.locator('[data-training-next-hop="true"]')).toHaveCount(0);
  await expect(training.locator(".training-current__more")).toHaveCount(0);
  await expect(training.locator(":scope > .training-carryover-row")).toHaveCount(0);
  const text = await training.innerText();
  for (const leakedEnglish of [
    "Surfaced",
    "Continue in training",
    "Next hop materialized",
    "The single-card training surface",
  ]) {
    expect(text).not.toContain(leakedEnglish);
  }
}

for (const [language] of Object.entries(VIEW_LABELS)) {
  for (const width of VIEWPORT_WIDTHS) {
    test(`renders the standalone ${language} Training Preview at ${width}px`, async ({ page }) => {
      await openStandaloneTrainingPreview(page, language, width);
      await expectThreeLocalizedPrimaryDestinations(page, language);
      await expectCurrentTrainingCardFacts(page);
      await expectNoHorizontalOverflow(page);

      if (language === "es-ES") {
        await expectSpanishNextHopIsLocalized(page);
      }
    });
  }
}
