import { decodeTurnEvent } from "./events";
import { useLiveTurnStore } from "./store";
import { refreshAccessToken } from "../api/client";

type TerminalHandler = (turnId: string, sessionId: number) => void;
type EventSourceFactory = (url: string) => EventSource;
type AccessRecovery = () => Promise<void>;
const EVENT_SOURCE_CLOSED = 2;

export class TurnStreamManager {
  private readonly sources = new Map<string, EventSource>();
  private readonly observedTerminalTurns = new Set<string>();
  private readonly recoveryAttempted = new Set<string>();

  constructor(
    private readonly onTerminal: TerminalHandler = () => undefined,
    private readonly createSource: EventSourceFactory = (url) => new EventSource(url),
    private readonly recoverAccess: AccessRecovery = refreshAccessToken,
  ) {}

  connect(turnId: string, sessionId: number): void {
    if (this.sources.has(turnId) || this.observedTerminalTurns.has(turnId)) return;
    const store = useLiveTurnStore.getState();
    store.ensureTurn(turnId, sessionId);
    store.setConnection(turnId, "connecting");
    const cursor = useLiveTurnStore.getState().turns[turnId]?.lastSeq ?? 0;
    const source = this.createSource(
      `/api/turns/${encodeURIComponent(turnId)}/events?after_seq=${cursor}`,
    );
    this.sources.set(turnId, source);

    source.onopen = () => {
      this.recoveryAttempted.delete(turnId);
      useLiveTurnStore.getState().setConnection(turnId, "open");
    };
    source.onerror = () => {
      if (source.readyState === EVENT_SOURCE_CLOSED) {
        void this.recoverClosedStream(turnId, sessionId, source);
      } else {
        useLiveTurnStore.getState().setConnection(turnId, "reconnecting");
      }
    };
    source.addEventListener("turn_event", (message) => {
      try {
        const event = decodeTurnEvent(JSON.parse((message as MessageEvent<string>).data));
        useLiveTurnStore.getState().applyEvent(event);
        if (event.type === "turn_terminal") {
          this.observedTerminalTurns.add(turnId);
          this.onTerminal(turnId, sessionId);
          this.close(turnId);
        }
      } catch {
        useLiveTurnStore.getState().setStreamError(
          turnId,
          "实时连接返回了无法识别的数据。请刷新页面，从服务器恢复当前回答。",
        );
        this.close(turnId);
      }
    });
  }

  close(turnId: string): void {
    const source = this.sources.get(turnId);
    if (source === undefined) return;
    source.close();
    this.sources.delete(turnId);
    useLiveTurnStore.getState().setConnection(turnId, "closed");
  }

  closeAll(): void {
    for (const turnId of [...this.sources.keys()]) this.close(turnId);
  }

  has(turnId: string): boolean {
    return this.sources.has(turnId) || this.observedTerminalTurns.has(turnId);
  }

  private async recoverClosedStream(
    turnId: string,
    sessionId: number,
    source: EventSource,
  ): Promise<void> {
    if (this.sources.get(turnId) !== source) return;
    source.close();
    this.sources.delete(turnId);
    useLiveTurnStore.getState().setConnection(turnId, "reconnecting");
    if (this.recoveryAttempted.has(turnId)) {
      this.failAuthenticationRecovery(turnId);
      return;
    }
    this.recoveryAttempted.add(turnId);
    try {
      await this.recoverAccess();
      this.connect(turnId, sessionId);
    } catch {
      this.failAuthenticationRecovery(turnId);
    }
  }

  private failAuthenticationRecovery(turnId: string): void {
    useLiveTurnStore.getState().setStreamError(
      turnId,
      "登录已过期，请重新登录后继续。",
    );
    window.dispatchEvent(new Event("amadeus:auth-expired"));
  }
}
