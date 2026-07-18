export const THEME_MODE_STORAGE_KEY = "amadeus:theme-mode:v1";

export type ThemeMode = "system" | "light" | "dark";

export function readThemeMode(storage: Pick<Storage, "getItem"> = window.localStorage): ThemeMode {
  try {
    const value = storage.getItem(THEME_MODE_STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}
