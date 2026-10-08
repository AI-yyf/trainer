const { test, expect } = require('playwright/test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
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

const nativeContent = readFileSync(resolve(__dirname, '../extension/src/core/webviewContent.ts'), 'utf8');
const nativeRootStyle = nativeContent.match(/html, body, #root \{[^}]+\}/)?.[0];
if (!nativeRootStyle) throw new Error('Native webview root styles must be exercised by the theme contract.');

function rgb(hex) {
  return `rgb(${[1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16)).join(', ')})`;
}
function contrast(foreground, background) {
  const luminance = color => color.match(/\d+/g).slice(0, 3).map(value => {
    const channel = Number(value) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}
async function actualInk(page) {
  return page.evaluate(() => {
    const shell = document.querySelector('.trainer-shell');
    const style = getComputedStyle(shell);
    const consumer = document.querySelector('[data-template=SettingsDetail]');
    return { foreground: style.color, background: style.backgroundColor,
      consumerForeground: getComputedStyle(consumer).color,
      fg: style.getPropertyValue('--fg-0').trim(), bg: style.getPropertyValue('--bg-0').trim(),
      hostBackground: document.body.style.getPropertyValue('--vscode-sideBar-background'),
      hostForeground: document.body.style.getPropertyValue('--vscode-sideBar-foreground') };
  });
}

for (const language of ['zh-CN', 'en-US']) {
  for (const width of [340, 460]) {
    test(`native root cascade preserves readable explicit and automatic theme ink: ${language}, ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 820 });
      await page.goto(`/vscode-preview.html?view=settings&lang=${language}&connection=connected&run=native-theme-${language}-${width}`);
      await openSettingsCategory(page, 'preferences');
      // The installed host appends this rule after the bundled webview CSS.
      await page.addStyleTag({ content: nativeRootStyle });
      const labels = language === 'zh-CN' ? ['浅色', '深色', '跟随系统'] : ['Light', 'Dark', 'System'];
      await hostTheme(page, 'dark', '#18212b', '#ccddee');
      await chooseTheme(page, labels[0]);
      await expect.poll(async () => (await actualInk(page)).foreground).toBe(rgb('#1f1f1f'));
      let ink = await actualInk(page);
      expect(ink.background).toBe(rgb('#ffffff'));
      expect(ink.consumerForeground).toBe(ink.foreground);
      expect(contrast(ink.foreground, ink.background)).toBeGreaterThanOrEqual(4.5);
      expect(ink.hostBackground).toBe('#18212b'); expect(ink.hostForeground).toBe('#ccddee');
      // Host switching must not change the learner's explicit Trainer choice.
      await hostTheme(page, 'light', '#f1f2f3', '#212223');
      expect((await actualInk(page)).foreground).toBe(ink.foreground);
      await chooseTheme(page, labels[1]);
      await expect.poll(async () => (await actualInk(page)).foreground).toBe(rgb('#efefef'));
      ink = await actualInk(page);
      expect(ink.background).toBe(rgb('#121212'));
      expect(ink.consumerForeground).toBe(ink.foreground);
      expect(contrast(ink.foreground, ink.background)).toBeGreaterThanOrEqual(4.5);
      expect(ink.hostBackground).toBe('#f1f2f3'); expect(ink.hostForeground).toBe('#212223');
      await chooseTheme(page, labels[2]);
      await expect.poll(async () => (await actualInk(page)).foreground).toBe(rgb('#212223'));
      expect((await actualInk(page)).background).toBe(rgb('#f1f2f3'));
      await hostTheme(page, 'dark', '#18212b', '#ccddee');
      await expect.poll(async () => (await actualInk(page)).foreground).toBe(rgb('#ccddee'));
      ink = await actualInk(page);
      expect(ink.background).toBe(rgb('#18212b'));
      expect(ink.consumerForeground).toBe(ink.foreground);
      expect(contrast(ink.foreground, ink.background)).toBeGreaterThanOrEqual(4.5);
    });
  }
}
