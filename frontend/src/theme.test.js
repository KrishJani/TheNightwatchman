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
