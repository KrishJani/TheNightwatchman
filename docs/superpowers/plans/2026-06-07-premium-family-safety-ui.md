# Premium Family Safety UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a premium, calm, lively landing page and live console for The Nightwatchman with light/dark mode and a custom Living Signal background.

**Architecture:** Preserve the current Vite/React single-page structure and existing backend/WebSocket behavior. Add a focused theme utility with Node tests, then reorganize `App` into semantic landing-page sections and replace the stylesheet with a responsive theme-driven visual system.

**Tech Stack:** React, Vite, CSS custom properties, browser `localStorage`, browser `matchMedia`, Node test runner.

---

### Task 1: Theme Utility

**Files:**
- Create: `frontend/src/theme.js`
- Create: `frontend/src/theme.test.js`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write failing tests for theme initialization**

```js
import test from "node:test";
import assert from "node:assert/strict";
import { getInitialTheme, getNextTheme, isTheme } from "./theme.js";

test("accepts only light and dark themes", () => {
  assert.equal(isTheme("light"), true);
  assert.equal(isTheme("dark"), true);
  assert.equal(isTheme("sepia"), false);
  assert.equal(isTheme(null), false);
});

test("uses saved theme when it is valid", () => {
  assert.equal(
    getInitialTheme({
      savedTheme: "dark",
      systemPrefersDark: false,
    }),
    "dark",
  );
});

test("falls back to system dark preference when no saved theme exists", () => {
  assert.equal(
    getInitialTheme({
      savedTheme: null,
      systemPrefersDark: true,
    }),
    "dark",
  );
});

test("defaults to light when saved theme is invalid and system is light", () => {
  assert.equal(
    getInitialTheme({
      savedTheme: "blue",
      systemPrefersDark: false,
    }),
    "light",
  );
});

test("toggles between light and dark", () => {
  assert.equal(getNextTheme("light"), "dark");
  assert.equal(getNextTheme("dark"), "light");
});
```

- [ ] **Step 2: Run tests and verify they fail because `theme.js` is missing**

Run: `npm --prefix frontend test`

Expected: FAIL with a module-not-found error for `frontend/src/theme.js`.

- [ ] **Step 3: Implement the theme utility**

```js
export const THEME_STORAGE_KEY = "nightwatchman-theme";

export function isTheme(value) {
  return value === "light" || value === "dark";
}

export function getInitialTheme({ savedTheme, systemPrefersDark }) {
  if (isTheme(savedTheme)) {
    return savedTheme;
  }

  return systemPrefersDark ? "dark" : "light";
}

export function getNextTheme(currentTheme) {
  return currentTheme === "dark" ? "light" : "dark";
}
```

- [ ] **Step 4: Add the test script**

`frontend/package.json` should include:

```json
"test": "node --test src/theme.test.js"
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `npm --prefix frontend test`

Expected: PASS.

### Task 2: Landing Page And Console Structure

**Files:**
- Modify: `frontend/src/main.jsx`

- [ ] **Step 1: Import theme helpers**

```js
import { getInitialTheme, getNextTheme, THEME_STORAGE_KEY } from "./theme";
```

- [ ] **Step 2: Add theme state and persistence**

Add state initialized from `localStorage` and `matchMedia`, apply `data-theme` to `document.documentElement`, and persist explicit toggles to `localStorage`.

- [ ] **Step 3: Add static product data arrays**

Define promise cards, agent cards, and protection steps near the top of `main.jsx`.

- [ ] **Step 4: Replace the returned markup with semantic sections**

Build these sections while preserving the existing state and handlers:

- App background and animated Living Signal layers.
- Navigation with anchor links and theme toggle.
- Hero with headline `A trusted voice beside every call.`
- Product promise cards.
- Multi-agent constellation for Sentinel, Verifier, Ally, Coach, and Scribe.
- How protection works.
- Live monitoring console containing existing status, start/end call, risk, transcript, coaching, ally alert, and outcome UI.
- Trust/privacy section.

- [ ] **Step 5: Verify existing behavior still has UI targets**

Confirm the JSX still renders known scammer, scam confirmed, clean call, error, coaching tip, ally alert, transcript, risk gauge, verification tags, and report download link.

### Task 3: Premium Visual System

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Replace the current stylesheet with theme tokens**

Use CSS custom properties for surface, text, accent, warning, danger, glass, and shadow tokens under light and dark themes.

- [ ] **Step 2: Implement the Living Signal background**

Use layered pseudo-elements, animated rings, drifting signal nodes, and subtle connection-line effects. Use risk state classes from the app to warm the accent color as risk rises.

- [ ] **Step 3: Style landing sections**

Create responsive layouts for nav, hero, cards, agent constellation, protection flow, live console, banners, transcript, and trust section.

- [ ] **Step 4: Add motion and accessibility constraints**

Add focus-visible states, hover states, responsive breakpoints, and `@media (prefers-reduced-motion: reduce)` rules to disable continuous animation.

### Task 4: Metadata And Verification

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Update metadata**

Set the title to `The Nightwatchman` and add a concise description meta tag.

- [ ] **Step 2: Run tests**

Run: `npm --prefix frontend test`

Expected: PASS.

- [ ] **Step 3: Run build**

Run: `npm --prefix frontend run build`

Expected: PASS and Vite emits `frontend/dist`.

- [ ] **Step 4: Check lints/diagnostics**

Run IDE diagnostics for edited files and fix introduced issues.

### Self-Review Notes

This plan covers the approved spec: landing page, revised headline, multi-agent presentation, light/dark mode, Living Signal background, existing behavior preservation, and verification. There are no placeholders or backend requirements.
