import { createEffect, Component, createSignal, For } from "solid-js";
import { createWebSocket } from "./websocket";

const App: Component = () => {
  const ws = createWebSocket("ws://127.0.0.1:8000");
  const [messages, setMessages] = createSignal<string[]>([]);

  createEffect(() => {
    const data = ws.data();
    console.log(ws.data())
    if (data) {
      setMessages((prev) => [...prev, data]);
    }
  });

  return (
    <p class="text-4xl text-green-700 text-center py-20">
      <For each={messages()}>{(msg) => <li>{msg}</li>}</For>
    </p>
  );
};

export default App;
