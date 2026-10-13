// A controllable EventSource stand-in for tests. Instances register themselves by URL so
// a test can push messages or simulate a dropped connection.

type Listener = (ev: Event) => void;

export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static byUrl(url: string): FakeEventSource | undefined {
    return [...FakeEventSource.instances].reverse().find((i) => i.url === url);
  }
  static allByUrl(url: string): FakeEventSource[] {
    return FakeEventSource.instances.filter((i) => i.url === url);
  }
  static reset(): void {
    FakeEventSource.instances = [];
  }

  url: string;
  readyState = 0;
  onopen: Listener | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: Listener | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
    // open on the next tick, like a real connection
    queueMicrotask(() => this.open());
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  emit(data: unknown): void {
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    this.onmessage?.(new MessageEvent("message", { data: payload }));
  }
  fail(): void {
    this.readyState = 2;
    this.onerror?.(new Event("error"));
  }
  close(): void {
    this.readyState = 2;
  }
  addEventListener(): void {}
  removeEventListener(): void {}
}

export function installFakeEventSource(): void {
  FakeEventSource.reset();
  (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
}
