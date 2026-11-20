const { expect } = require("playwright/test");

/**
 * Workbench navigation contract (Phase 0).
 *
 * The workbench has exactly two primary destinations — Chat and Resources.
 * Learning is no longer a destination: it is a drawer opened from the header
 * icon beside the session-history utility, plus a state strip above the
 * conversation.
 *
 * Legacy routes (plan / training / progress) remain valid commands, deep
 * links and restore values. They resolve to Chat with the learning drawer
 * opened on the matching section, so old entry points keep working without
 * ever mounting a Learning page.
 */

/** The two primary destinations, in navigation order. */
const PRIMARY_DESTINATIONS = ["coach", "resources"];

/** Legacy route → the learning drawer section it opens. */
const LEGACY_ROUTE_SECTIONS = {
  plan: "goal",
  training: "practice",
  progress: "progress",
};

const LEARNING_TOGGLE = "trainer-learning-toggle";

/**
 * Open the learning drawer. Legacy routes land on their own section; the
 * plain toggle keeps the section the learner last used.
 */
async function openLearningDrawer(page, section) {
  const toggle = page.getByTestId(LEARNING_TOGGLE);
  await expect(toggle).toBeVisible();
  await toggle.click();
  const drawer = page.locator('[data-template="LearningDrawer"]');
  await expect(drawer).toBeVisible();
  if (section) {
    await expect(page.locator(`[data-learning-section="${section}"]`)).toBeVisible();
  }
  return drawer;
}

/**
 * Close the learning drawer if it is open. A legacy learning route opens the
 * drawer as soon as the app restores, so wait for it to appear before closing.
 */
async function closeLearningDrawer(page) {
  const drawer = page.locator('[data-template="LearningDrawer"]');
  await drawer.waitFor({ state: "attached", timeout: 5000 }).catch(() => undefined);
  if (await drawer.count()) {
    const close = page.locator('.app-shell-overlay__close');
    if (await close.count()) await close.first().click();
  }
  await expect(page.locator('[data-template="LearningDrawer"]')).toHaveCount(0);
}

/**
 * Assert the two-destination contract: exactly Chat and Resources in the nav,
 * plus the learning, history and settings utilities in the header.
 */
async function expectTwoPrimaryDestinations(page) {
  const tabs = page.locator(".app-shell-nav button");
  await expect(tabs).toHaveCount(2);
  await expect(tabs.nth(0)).toHaveAttribute("data-testid", "trainer-view-nav-coach");
  await expect(tabs.nth(1)).toHaveAttribute("data-testid", "trainer-view-nav-resources");
  await expect(page.getByTestId(LEARNING_TOGGLE)).toBeVisible();
  await expect(page.getByTestId("trainer-history-toggle")).toBeVisible();
  await expect(page.getByTestId("trainer-view-nav-settings")).toBeVisible();
}

/**
 * Assert which primary destination is current. Legacy learning routes resolve
 * to Chat, so they assert the Chat nav item plus the open drawer.
 */
async function expectActiveDestination(page, destination) {
  const resolved = destination === "plan" || destination === "training" || destination === "progress"
    ? "coach"
    : destination;
  await expect(page.getByTestId(`trainer-view-nav-${resolved}`)).toHaveAttribute("aria-current", "page");
  if (destination !== "coach" && destination !== "resources" && destination !== "settings") {
    await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  }
}

/**
 * Navigate the way a learner does: Chat and Resources are nav items; the
 * learning content is reached through the header icon.
 */
async function navigateTo(page, destination) {
  if (destination === "coach" || destination === "resources" || destination === "settings") {
    await closeLearningDrawer(page);
    await page.getByTestId(`trainer-view-nav-${destination}`).click();
    return;
  }
  await openLearningDrawer(page, LEGACY_ROUTE_SECTIONS[destination]);
}

module.exports = {
  PRIMARY_DESTINATIONS,
  LEGACY_ROUTE_SECTIONS,
  closeLearningDrawer,
  expectActiveDestination,
  expectTwoPrimaryDestinations,
  navigateTo,
  openLearningDrawer,
};
