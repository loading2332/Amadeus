import {
  readSidebarCollapsed,
  SIDEBAR_COLLAPSED_STORAGE_KEY,
  writeSidebarCollapsed,
} from "./sidebarPreference";

describe("desktop sidebar preference", () => {
  it("accepts only the explicit collapsed value", () => {
    expect(readSidebarCollapsed({ getItem: () => "true" })).toBe(true);
    expect(readSidebarCollapsed({ getItem: () => "false" })).toBe(false);
    expect(readSidebarCollapsed({ getItem: () => "damaged" })).toBe(false);
  });

  it("survives unavailable browser storage", () => {
    expect(readSidebarCollapsed({ getItem: () => { throw new Error("blocked"); } })).toBe(false);
    expect(() => writeSidebarCollapsed(true, { setItem: () => { throw new Error("blocked"); } })).not.toThrow();
  });

  it("writes a versioned boolean preference", () => {
    const setItem = vi.fn();
    writeSidebarCollapsed(true, { setItem });
    expect(setItem).toHaveBeenCalledWith(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    expect(SIDEBAR_COLLAPSED_STORAGE_KEY).toBe("amadeus:sidebar-collapsed:v1");
  });
});
