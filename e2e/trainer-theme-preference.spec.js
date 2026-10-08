const { test, expect } = require('playwright/test');
const { openSettingsCategory } = require('./template-navigation');

async function hostTheme(page, family, background, foreground) {
  await page.evaluate(({ family, background, foreground }) => {
    document.body.className = `vscode-${family}`;
    document.body.setAttribute('data-vscode-theme-kind', family);
    document.body.style.setProperty('--vscode-sideBar-background', background);
    document.body.style.setProperty('--vscode-sideBar-foreground', foreground);
  }, { family, background, foreground });
}
async function colors(page) {
  return page.evaluate(() => {
    const computed = getComputedStyle(document.body);
    return { theme: document.documentElement.dataset.theme,
      background: computed.backgroundColor, foreground: computed.color,
      bg: computed.getPropertyValue('--bg-0').trim(), fg: computed.getPropertyValue('--fg-0').trim(),
      rootOverride: document.documentElement.style.getPropertyValue('--bg-0'),
      bodyOverride: document.body.style.getPropertyValue('--bg-0'),
      hostBackground: document.body.style.getPropertyValue('--vscode-sideBar-background') };
  });
}
async function chooseTheme(page, name) {
  const theme = page.locator('[data-settings-subsection=appearance] .settings-choice').first();
  await theme.locator('.settings-choice__trigger').click();
  await theme.getByRole('option', { name, exact: true }).click();
  await expect(theme.locator('.settings-choice__trigger')).toHaveText(name);
}

test('explicit Light and Dark choices change actual colors while Auto follows live host tokens', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=explicit-theme-contract');
  await openSettingsCategory(page, 'preferences');
  await hostTheme(page, 'dark', '#18212b', '#ccddee');
  await chooseTheme(page, 'Light');
  await expect.poll(async () => (await colors(page)).theme).toBe('light');
  const light = await colors(page);
  expect(light.background).not.toBe('rgb(24, 33, 43)');
  expect(light.foreground).not.toBe('rgb(204, 221, 238)');
  expect(light.bg).toBe(light.bodyOverride);
  expect(light.rootOverride).toBe(light.bodyOverride);
  expect(light.hostBackground).toBe('#18212b');
  await hostTheme(page, 'light', '#f1f2f3', '#212223');
  await expect.poll(async () => (await colors(page)).background).toBe(light.background);
  await chooseTheme(page, 'Dark');
  await expect.poll(async () => (await colors(page)).theme).toBe('dark');
  const dark = await colors(page);
  expect(dark.background).not.toBe(light.background);
  expect(dark.foreground).not.toBe(light.foreground);
  await chooseTheme(page, 'System');
  await expect.poll(async () => (await colors(page)).background).toBe('rgb(241, 242, 243)');
  const auto = await colors(page);
  expect(auto.rootOverride).toBe(''); expect(auto.bodyOverride).toBe('');
  expect(auto.fg).toBe('#212223');
  await hostTheme(page, 'dark', '#18212b', '#ccddee');
  await expect.poll(async () => (await colors(page)).background).toBe('rgb(24, 33, 43)');
  await expect.poll(async () => (await colors(page)).theme).toBe('dark');
});
