import { installChromeSidePanelTransport } from "./lib/chromeSidePanelTransport";
import { mountWorkbenchApp, renderStartupFailure } from "./bootstrapWorkbench";

void installChromeSidePanelTransport()
  .then(() => mountWorkbenchApp())
  .catch((error) => {
    renderStartupFailure(error);
  });
