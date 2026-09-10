import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/?live=1&sidecarPort=34901", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
await page.getByRole("button", { name: "Settings", exact: true }).first().click();
await page.waitForTimeout(1100);
await page.screenshot({ path: "/tmp/trainer_shots/n2-settings-quicksetup.png" });
// paste blob into quick setup paste field
const blob = JSON.stringify({_type:"newapi_channel_conn", key:"sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS", url:"http://minimax.redfast.top"});
const pasteField = page.getByPlaceholder(/Paste .* connection info/).first();
await pasteField.click();
await pasteField.fill(blob);
await page.waitForTimeout(400);
await page.screenshot({ path: "/tmp/trainer_shots/n2-settings-pasted.png" });
// paste key into key field
await page.getByPlaceholder(/Paste your key/).first().fill("sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS");
await page.waitForTimeout(300);
await page.getByRole("button", { name: /Save & connect/ }).click();
await page.waitForTimeout(12000);
await page.screenshot({ path: "/tmp/trainer_shots/n2-settings-saved.png" });
console.log("done");
await browser.close();
