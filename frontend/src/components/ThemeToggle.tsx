"use client";

import { useEffect, useSyncExternalStore } from "react";

import {
  THEME_CHANGE_EVENT,
  THEME_ORDER,
  type ThemePreference,
  applyTheme,
  readStoredPreference,
  resolveTheme,
  storePreference,
} from "@/lib/theme";

const LABELS: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

const ICONS: Record<ThemePreference, string> = {
  system: "◐", // half-filled circle
  light: "☀", // sun
  dark: "☽", // moon
};

/**
 * The stored preference is external state, so it is read through
 * useSyncExternalStore rather than copied into component state by an effect.
 * That keeps it correct across tabs for free, and avoids setting state during
 * an effect, which the React Compiler rules reject.
 */
function subscribe(onChange: () => void): () => void {
  // `storage` fires in other tabs; the custom event covers this one.
  window.addEventListener("storage", onChange);
  window.addEventListener(THEME_CHANGE_EVENT, onChange);

  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(THEME_CHANGE_EVENT, onChange);
  };
}

export function ThemeToggle() {
  const preference = useSyncExternalStore(
    subscribe,
    readStoredPreference,
    // The server cannot know the choice; the inline script has already applied
    // the right colours, so only this label is briefly generic.
    () => "system" as ThemePreference,
  );

  // While following the system, track changes to it live rather than only on
  // reload. Registers a listener and sets no state, so the rule above holds.
  useEffect(() => {
    if (preference !== "system") {
      return;
    }

    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => applyTheme(resolveTheme("system"));

    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, [preference]);

  function cycle() {
    const next =
      THEME_ORDER[(THEME_ORDER.indexOf(preference) + 1) % THEME_ORDER.length];

    storePreference(next);
    applyTheme(resolveTheme(next));
    window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
  }

  return (
    <button
      type="button"
      onClick={cycle}
      data-testid="theme-toggle"
      data-theme-preference={preference}
      // Announces the action, since the visible label is the current state.
      aria-label={`Theme: ${LABELS[preference]}. Click to change.`}
      title={`Theme: ${LABELS[preference]}`}
      className="flex items-center gap-1.5 rounded-md border border-black/15 px-2.5 py-1 text-xs transition-opacity hover:opacity-70 dark:border-white/20"
    >
      <span aria-hidden="true" suppressHydrationWarning>
        {ICONS[preference]}
      </span>
      <span suppressHydrationWarning>{LABELS[preference]}</span>
    </button>
  );
}
