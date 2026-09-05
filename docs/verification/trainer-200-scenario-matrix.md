# Trainer 200-Scenario Experience Matrix

This matrix turns the Trainer product constitution into 200 executable browser journeys. The canonical records live in [trainer-experience-matrix.js](../../e2e/trainer-experience-matrix.js); the test suite opens the real webview Preview for every record and performs a user-visible interaction before checking layout and console health.

## Evidence Rule

`PW` means a real browser session against the built webview Preview. It proves the rendered interface, navigation, input, focusable surfaces, layout, and client-side recovery state. It does not replace the installed VSIX or a real Provider result. Existing VSIX and Provider smoke flows remain required evidence for the relevant high-risk journeys.

## Coverage

| IDs | Count | User journey focus | Primary interaction |
| --- | ---: | --- | --- |
| `C01-C34` | 34 | Coach, first look, conversation, provider recovery | Open Coach and write a real draft when allowed |
| `P01-P34` | 34 | Mainline, evidence, blocker, frozen and project plans | Open the current plan and reveal its next detail |
| `R01-R38` | 38 | Library, search, provenance, sandbox, restore | Select a resource and search it |
| `T01-T44` | 44 | Learn-first cards, verification, transfer, localization | Inspect one current card and its five facts |
| `S01-S20` | 20 | Provider truth, recovery, protocol and settings | Open connection details deliberately |
| `X01-X30` | 30 | Localization, themes, narrow widths and handoffs | Navigate between two top-level views |
| **Total** | **200** | Five views plus cross-view recovery | Browser-rendered user journeys |

Each scenario records an ID, user goal, target view, initial Preview state, locale, viewport, theme, requirement tags, and runner. The matrix deliberately has unique `run` URLs so browser storage from one journey cannot make another look healthy.

## Run

```powershell
npm run test:experience-matrix
```

The release evidence must also include the installed VSIX checks and a small set of real Provider journeys. Never count a Preview pass as proof that the VS Code host, sidecar, or Provider path also passed.
