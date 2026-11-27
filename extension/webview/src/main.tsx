import { mountWorkbenchApp,renderStartupFailure } from "./bootstrapWorkbench";

void mountWorkbenchApp().catch((error) => {
  renderStartupFailure(error);
});
