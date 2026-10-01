import { authHeaders, signalUnauthorized } from "./client";

export type StreamStatus = "connecting" | "live" | "reconnecting";

/**
 * GET /api/stream over fetch, not EventSource: EventSource can't send an
 * Authorization header, and a token in the URL would end up in logs and history.
 * Reconnects with backoff; returns a function that closes it for good.
 */
export function openStream(
  onEvent: (event: string, data: unknown) => void,
  onStatus: (status: StreamStatus) => void,
): () => void {
  let stopped = false;
  let controller = new AbortController();

  const run = async () => {
    let delay = 1000;
    while (!stopped) {
      controller = new AbortController();
      try {
        onStatus(delay === 1000 ? "connecting" : "reconnecting");
        const res = await fetch("/api/stream", { headers: authHeaders(), signal: controller.signal });
        if (res.status === 401) {
          signalUnauthorized();
          return;
        }
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        onStatus("live");
        delay = 1000;
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value;
          let end: number;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            let event = "message";
            let data = "";
            for (const line of frame.split("\n")) {
              if (line.startsWith("event: ")) event = line.slice(7);
              else if (line.startsWith("data: ")) data += line.slice(6);
            }
            if (data) onEvent(event, JSON.parse(data));
          }
        }
      } catch {
        if (stopped) return;
      }
      onStatus("reconnecting");
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 30_000);
    }
  };

  void run();
  return () => {
    stopped = true;
    controller.abort();
  };
}
