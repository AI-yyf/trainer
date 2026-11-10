"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { vscodeElectronCandidates, resolveVSCodeElectronBinary } = require(
  "../../scripts/vscode-electron.mjs",
);

test("darwin candidates cover both the legacy Electron and current Code binary", () => {
  const candidates = vscodeElectronCandidates({
    platform: "darwin",
    env: {},
    home: "/Users/learner",
  });
  assert.ok(candidates.includes("/Applications/Visual Studio Code.app/Contents/MacOS/Electron"));
  assert.ok(candidates.includes("/Applications/Visual Studio Code.app/Contents/MacOS/Code"));
  // Candidate paths belong to the target platform, so a Windows CI host must
  // still produce POSIX darwin paths (not backslash-joined ones).
  assert.ok(candidates.every((candidate) => candidate.startsWith("/")));
});

test("darwin resolves Code when the legacy Electron binary is gone", () => {
  const code = "/Applications/Visual Studio Code.app/Contents/MacOS/Code";
  const resolved = resolveVSCodeElectronBinary({
    platform: "darwin",
    env: {},
    home: "/Users/learner",
    exists: (candidate) => candidate === code,
  });
  assert.equal(resolved, code);
});

test("the explicit override wins before platform conventions", () => {
  const override = "/opt/custom/Code";
  const resolved = resolveVSCodeElectronBinary({
    platform: "darwin",
    env: { TRAINER_VSCODE_ELECTRON: override },
    home: "/Users/learner",
    exists: (candidate) => candidate === override,
  });
  assert.equal(resolved, override);
});

test("linux candidates include the package-managed binaries", () => {
  const candidates = vscodeElectronCandidates({ platform: "linux", env: {}, home: "/home/x" });
  assert.deepEqual(candidates, ["/usr/share/code/code", "/usr/bin/code", "/snap/bin/code"]);
});

test("win32 candidates come from LOCALAPPDATA and Program Files", () => {
  const candidates = vscodeElectronCandidates({
    platform: "win32",
    env: { LOCALAPPDATA: "C:\\Users\\Learner\\AppData\\Local" },
    home: "C:\\Users\\Learner",
  });
  assert.ok(candidates[0].endsWith("Microsoft VS Code\\Code.exe"));
  assert.ok(candidates[1].includes("Program Files"));
  assert.ok(candidates.every((candidate) => !candidate.includes("/")));
});

test("no installation resolves to null instead of a dead path", () => {
  const resolved = resolveVSCodeElectronBinary({
    platform: "darwin",
    env: {},
    home: "/Users/learner",
    exists: () => false,
  });
  assert.equal(resolved, null);
});
