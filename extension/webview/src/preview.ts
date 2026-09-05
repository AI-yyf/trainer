import {
  installBrowserPreviewEnvironment,
  installBrowserPreviewHarness,
} from "./lib/browserPreviewHarness";

document.documentElement.dataset.trainerPreview = "sidebar";

const previewSearch = new URLSearchParams(window.location.search);

if (previewSearch.get("live") === "1") {
  installBrowserPreviewEnvironment();
} else {
  installBrowserPreviewHarness();
}

void import("./main");
