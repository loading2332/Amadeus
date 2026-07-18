import { queryClient } from "./queryClient";
import { queryKeys } from "../api/queryKeys";
import { TurnStreamManager } from "../streaming/manager";
import { useLiveTurnStore } from "../streaming/store";

export async function handOffTerminalTurn(
  refreshAuthoritativeState: () => Promise<unknown>,
  removeLiveOverlay: () => void,
): Promise<void> {
  await refreshAuthoritativeState();
  removeLiveOverlay();
}

export const turnStreamManager = new TurnStreamManager((turnId, sessionId) => {
  void handOffTerminalTurn(
    () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.turn(turnId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.turns(sessionId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.messages(sessionId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions }),
      ]),
    () => useLiveTurnStore.getState().removeTurn(turnId),
  ).catch(() => undefined);
});
