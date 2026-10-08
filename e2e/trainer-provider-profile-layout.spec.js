const { test, expect } = require('playwright/test');
const { openSettingsCategory } = require('./template-navigation');

// Browser fixtures establish readable layout; native installed-provider tests
// independently establish that saved model and connection facts are genuine.
for (const language of ['zh-CN', 'en-US', 'de-DE']) {
  for (const width of [299, 340, 460]) {
    test(`saved connection keeps model readable beside actions: ${language}, ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 820 });
      await page.goto(`/vscode-preview.html?view=settings&lang=${language}&connection=connected&run=provider-bar-${language}-${width}`);
      await openSettingsCategory(page, 'connection');
      const bar = page.locator('.settings-provider-bar');
      await expect(bar).toBeVisible();
      const bounds = await bar.evaluate(element => {
        const rect = element.getBoundingClientRect();
        const model = element.querySelector('.settings-provider-profile__model');
        const modelRect = model.getBoundingClientRect();
        return { width: rect.width, modelWidth: modelRect.width, modelHeight: modelRect.height,
          lineHeight: parseFloat(getComputedStyle(model).lineHeight),
          modelText: model.textContent,
          controls: [...element.querySelectorAll('button')].map(button => {
            const bounds = button.getBoundingClientRect();
            return { x: bounds.left - rect.left, right: bounds.right - rect.left,
              width: bounds.width, disabled: button.disabled };
          }) };
      });
      expect(bounds.modelText).toBe('gpt-4.1-mini-compatible');
      expect(bounds.modelWidth).toBeGreaterThanOrEqual(120);
      expect(bounds.modelHeight).toBeLessThanOrEqual(bounds.lineHeight * 3 + 1);
      for (const control of bounds.controls) {
        expect(control.x).toBeGreaterThanOrEqual(-1);
        expect(control.right).toBeLessThanOrEqual(bounds.width + 1);
        expect(control.width).toBeGreaterThan(20);
      }
      const editName = { 'zh-CN': '编辑配置', 'en-US': 'Edit configuration', 'de-DE': 'Konfiguration bearbeiten' }[language];
      await bar.getByRole('button', { name: editName, exact: true }).click();
      await expect(page.locator('form.settings-sheet__minor-body')).toBeVisible();
    });
  }
}
