import { createSignal, onCleanup } from "solid-js";

export function createWebSocket(url: string) {
  const [data, setData] = createSignal<string | null>(null);

  const ws = new WebSocket(url);

  ws.onmessage = (e) => setData(e.data);

  onCleanup(() => ws.close());

  return {
    data,
    send: (msg: string) => ws.send(msg),
    close: () => ws.close(),
  };
}
