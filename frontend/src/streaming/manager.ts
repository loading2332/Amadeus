import { decodeTurnEvent } from "./events";
import { useLiveTurnStore } from "./store";

type TerminalHandler = (turnId: string, sessionId: number) => void;
type EventSourceFactory = (url: string) => EventSource;

export class TurnStreamManager {
  private readonly sources = new Map<string, EventSource>();
  private readonly observedTerminalTurns = new Set<string>();

  constructor(
    private readonly onTerminal: TerminalHandler = () => undefined,
    private readonly createSource: EventSourceFactory = (url) => new EventSource(url),
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

    source.onopen = () => useLiveTurnStore.getState().setConnection(turnId, "open");
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        this.close(turnId);
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
}
