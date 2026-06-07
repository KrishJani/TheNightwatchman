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
