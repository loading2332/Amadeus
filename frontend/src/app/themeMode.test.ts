import { readThemeMode, THEME_MODE_STORAGE_KEY } from "./themeMode";

describe("theme mode storage", () => {
  it.each(["light", "dark"] as const)("accepts %s", (mode) => {
    expect(readThemeMode({ getItem: () => mode })).toBe(mode);
  });

  it("falls back to dark for missing, legacy, damaged, or unavailable storage", () => {
    expect(readThemeMode({ getItem: () => null })).toBe("dark");
    expect(readThemeMode({ getItem: () => "system" })).toBe("dark");
    expect(readThemeMode({ getItem: () => "sepia" })).toBe("dark");
    expect(readThemeMode({ getItem: () => { throw new Error("blocked"); } })).toBe("dark");
    expect(THEME_MODE_STORAGE_KEY).toBe("amadeus:theme-mode:v1");
  });
});
