import { TurnStreamManager } from "./manager";
import { useLiveTurnStore } from "./store";

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private readonly listeners = new Map<string, (event: MessageEvent<string>) => void>();

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    this.listeners.set(type, listener as (event: MessageEvent<string>) => void);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(type: string, payload: unknown): void {
    this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(payload) }));
  }

  emitRaw(type: string, data: string): void {
    this.listeners.get(type)?.(new MessageEvent(type, { data }));
  }
}

describe("TurnStreamManager", () => {
  beforeEach(() => useLiveTurnStore.getState().reset());

  it("keeps one EventSource per turn under repeated connects", () => {
    const sources: FakeEventSource[] = [];
    const manager = new TurnStreamManager(undefined, (url) => {
      const source = new FakeEventSource(url);
      sources.push(source);
      return source as unknown as EventSource;
    });

    manager.connect("turn-1", 4);
    manager.connect("turn-1", 4);

    expect(sources).toHaveLength(1);
    expect(sources[0]?.url).toBe("/api/turns/turn-1/events?after_seq=0");
  });

  it("applies a terminal event before closing and notifying Query", () => {
    let source: FakeEventSource | undefined;
    const terminal = vi.fn();
    const manager = new TurnStreamManager(terminal, (url) => {
      source = new FakeEventSource(url);
      return source as unknown as EventSource;
    });
    manager.connect("turn-1", 4);
    source?.emit("turn_event", {
      seq: 1,
      type: "turn_terminal",
      turn_id: "turn-1",
      occurred_at: "2026-07-19T00:00:00Z",
      data: { status: "done" },
    });

    expect(useLiveTurnStore.getState().turns["turn-1"]?.status).toBe("done");
    expect(source?.closed).toBe(true);
    expect(terminal).toHaveBeenCalledWith("turn-1", 4);
  });

  it("surfaces a safe protocol error instead of silently closing", () => {
    let source: FakeEventSource | undefined;
    const manager = new TurnStreamManager(undefined, (url) => {
      source = new FakeEventSource(url);
      return source as unknown as EventSource;
    });
    manager.connect("turn-1", 4);
    source?.emitRaw("turn_event", "not-json");

    expect(useLiveTurnStore.getState().turns["turn-1"]?.streamError).toContain("无法识别");
    expect(source?.closed).toBe(true);
  });
});
