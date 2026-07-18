import { syncOwnerIdentity } from "./ownerIdentity";

describe("syncOwnerIdentity", () => {
  it("records the first owner without reporting a change", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
    expect(syncOwnerIdentity(7, storage)).toBe(false);
    expect(syncOwnerIdentity(7, storage)).toBe(false);
    expect(syncOwnerIdentity(8, storage)).toBe(true);
  });

  it("does not break startup when localStorage is unavailable", () => {
    expect(syncOwnerIdentity(7, {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    })).toBe(false);
  });
});
