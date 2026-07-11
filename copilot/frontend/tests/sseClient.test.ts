/**
 * iterateSse round-trip — feed a stream of SSE bytes and verify we yield
 * properly typed events. Mirrors the backend's tests/copilot/test_sse.py.
 */
import { describe, expect, it } from "vitest";
import { iterateSse, parseSseChunk } from "@/lib/sseClient";

function makeResponse(chunks: string[]): Response {
  const enc = new TextEncoder();
  const queue = [...chunks];
  const stream = new ReadableStream({
    pull(controller) {
      const next = queue.shift();
      if (next === undefined) { controller.close(); return; }
      controller.enqueue(enc.encode(next));
    },
  });
  // Response is fine to construct from a ReadableStream in jsdom.
  return new Response(stream, { status: 200 });
}

describe("parseSseChunk", () => {
  it("parses a single event with JSON data", () => {
    const evt = parseSseChunk('event: text\ndata: {"text":"hi"}');
    expect(evt).toEqual({ event: "text", data: { text: "hi" } });
  });
  it("returns null for empty data", () => {
    expect(parseSseChunk("event: noop\n")).toBeNull();
  });
});

describe("iterateSse", () => {
  it("yields events split across two chunks", async () => {
    const stream = makeResponse([
      'event: text\ndata: {"text":"hel',
      'lo"}\n\nevent: done\ndata: {"stop_reason":"end_turn"}\n\n',
    ]);
    const out: unknown[] = [];
    for await (const evt of iterateSse(stream)) {
      out.push(evt);
    }
    expect(out).toEqual([
      { event: "text", data: { text: "hello" } },
      { event: "done", data: { stop_reason: "end_turn" } },
    ]);
  });

  it("handles unicode characters", async () => {
    const stream = makeResponse([
      'event: text\ndata: {"text":"→ café 🎉"}\n\n',
    ]);
    const out: unknown[] = [];
    for await (const evt of iterateSse(stream)) {
      out.push(evt);
    }
    expect(out[0]).toEqual({ event: "text", data: { text: "→ café 🎉" } });
  });
});
