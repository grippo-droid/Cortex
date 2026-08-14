/**
 * Theme selection, persisted across visits (Frontend Spec section 7).
 *
 * Three choices rather than two: "system" is a real preference, and a plain
 * light/dark toggle throws it away the first time it is used.
 *
 * The resolved theme is applied as a class on <html> rather than left to the
 * `prefers-color-scheme` media query, because a media query cannot be
 * overridden by a user choice. `globals.css` declares the matching
 * `@custom-variant`, so every existing `dark:` utility follows the class.
 */

export const THEME_STORAGE_KEY = "cortex.theme";

/** Dispatched after a change so this tab re-reads; `storage` only fires in others. */
export const THEME_CHANGE_EVENT = "cortex:theme-change";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_ORDER: ThemePreference[] = ["system", "light", "dark"];

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

export function readStoredPreference(): ThemePreference {
  if (typeof window === "undefined") {
    return "system";
  }

  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    // Private mode and blocked storage both throw here. A theme is not worth
    // failing a page render over.
    return "system";
  }
}

export function storePreference(preference: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Preference simply will not persist; the current session still honours it.
  }
}

export function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

export function applyTheme(resolved: ResolvedTheme): void {
  document.documentElement.classList.toggle("dark", resolved === "dark");
  // Lets form controls and scrollbars match, which CSS variables alone miss.
  document.documentElement.style.colorScheme = resolved;
}

/**
 * Run before first paint, inlined into <head>.
 *
 * Without this the document renders with the default theme and then corrects
 * itself once React hydrates, which is a visible flash of the wrong colours on
 * every page load. Kept as a string because it has to execute synchronously,
 * ahead of the bundle.
 */
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    var preference = stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
    var resolved = preference === "system"
      ? (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : preference;
    if (resolved === "dark") document.documentElement.classList.add("dark");
    document.documentElement.style.colorScheme = resolved;
  } catch (e) {}
})();
`.trim();
