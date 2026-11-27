import { installChromeSidePanelTransport } from "./lib/chromeSidePanelTransport";

void installChromeSidePanelTransport().then(() => import("./main"));
