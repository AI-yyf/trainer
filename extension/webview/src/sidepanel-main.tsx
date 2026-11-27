import { mountWorkbenchApp,renderStartupFailure } from "./bootstrapWorkbench";
import { installChromeSidePanelTransport } from "./lib/chromeSidePanelTransport";

void installChromeSidePanelTransport()
  .then(() => mountWorkbenchApp())
  .catch((error) => {
    renderStartupFailure(error);
  });
