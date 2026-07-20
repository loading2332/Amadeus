export const THEME_MODE_STORAGE_KEY = "amadeus:theme-mode:v1";

export type ThemeMode = "light" | "dark";

export function readThemeMode(storage: Pick<Storage, "getItem"> = window.localStorage): ThemeMode {
  try {
    const value = storage.getItem(THEME_MODE_STORAGE_KEY);
    return value === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}
