/** A scriptable stand-in for EventSource (jsdom has none). Dispatches real MessageEvents. */
type Listener = (e: Event) => void

export class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly url: string
  readyState = 0 // CONNECTING
  closed = false
  private listeners = new Map<string, Listener[]>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  static reset() {
    FakeEventSource.instances = []
  }
  static get last(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1]!
  }

  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn])
  }
  removeEventListener() {}

  close() {
    this.closed = true
    this.readyState = 2
  }

  /** A named SSE event with a JSON body and an id. */
  emit(type: string, data: unknown, id?: number) {
    this.readyState = 1
    const e = new MessageEvent(type, {
      data: JSON.stringify(data),
      lastEventId: id === undefined ? '' : String(id),
    })
    for (const fn of this.listeners.get(type) ?? []) fn(e)
  }

  /** The built-in connection error: a plain Event, not a MessageEvent. */
  connectionError(state: 0 | 2 = 0) {
    this.readyState = state
    const e = new Event('error')
    for (const fn of this.listeners.get('error') ?? []) fn(e)
  }
}
