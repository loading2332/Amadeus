const OWNER_STORAGE_KEY = "amadeus:owner-id:v1";

export function syncOwnerIdentity(
  ownerUserId: number,
  storage: Pick<Storage, "getItem" | "setItem"> = window.localStorage,
): boolean {
  try {
    const previous = storage.getItem(OWNER_STORAGE_KEY);
    storage.setItem(OWNER_STORAGE_KEY, String(ownerUserId));
    return previous !== null && previous !== String(ownerUserId);
  } catch {
    return false;
  }
}

export function clearOwnerIdentity(
  storage: Pick<Storage, "removeItem"> = window.localStorage,
): void {
  try {
    storage.removeItem(OWNER_STORAGE_KEY);
  } catch {
    // Authentication still ends server-side when browser storage is unavailable.
  }
}
