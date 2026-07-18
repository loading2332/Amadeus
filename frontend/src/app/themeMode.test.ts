import { readThemeMode, THEME_MODE_STORAGE_KEY } from "./themeMode";

describe("theme mode storage", () => {
  it.each(["system", "light", "dark"] as const)("accepts %s", (mode) => {
    expect(readThemeMode({ getItem: () => mode })).toBe(mode);
  });

  it("falls back to system for damaged or unavailable storage", () => {
    expect(readThemeMode({ getItem: () => "sepia" })).toBe("system");
    expect(readThemeMode({ getItem: () => { throw new Error("blocked"); } })).toBe("system");
    expect(THEME_MODE_STORAGE_KEY).toBe("amadeus:theme-mode:v1");
  });
});
