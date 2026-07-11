/**
 * SSE parsing: works against both fetch().body streams (chat) and
 * EventSource (live training tail).
 *
 * For chat we use fetch+ReadableStream because EventSource cannot do POST.
 * `iterateSse` yields {event, data} objects as the stream flows.
 */
import type { StreamEvent } from "./types";

export async function* iterateSse(
  response: Response,
): AsyncGenerator<StreamEvent, void, unknown> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = findBoundary(buf)) !== -1) {
      const chunk = buf.slice(0, boundary);
      const boundaryLen = buf.startsWith("\r\n\r\n", boundary) ? 4 : 2;
      buf = buf.slice(boundary + boundaryLen);
      const parsed = parseSseChunk(chunk);
      if (parsed) yield parsed;
    }
  }
  if (buf.trim()) {
    const parsed = parseSseChunk(buf);
    if (parsed) yield parsed;
  }
}

function findBoundary(buf: string): number {
  const lf = buf.indexOf("\n\n");
  const crlf = buf.indexOf("\r\n\r\n");
  if (lf === -1) return crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}

export function parseSseChunk(raw: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.replace(/\r\n/g, "\n").split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  const data = dataLines.join("\n");
  if (!data) return null;
  try {
    const parsed = JSON.parse(data);
    return { event, data: parsed } as StreamEvent;
  } catch {
    return null;
  }
}
