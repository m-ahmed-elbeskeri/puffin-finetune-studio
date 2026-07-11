import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatStore } from "@/lib/stores/chatStore";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    chatStream: vi.fn(),
    truncateThread: vi.fn(),
  },
}));

const revalidateData = vi.fn();
vi.mock("@/lib/revalidate", () => ({
  revalidateData: () => revalidateData(),
}));

function makeResponse(chunks: string[]): Response {
  const enc = new TextEncoder();
  const queue = [...chunks];
  const stream = new ReadableStream({
    pull(controller) {
      const next = queue.shift();
      if (next === undefined) {
        controller.close();
        return;
      }
      controller.enqueue(enc.encode(next));
    },
  });
  return new Response(stream, { status: 200 });
}

describe("chatStore", () => {
  beforeEach(() => {
    useChatStore.setState({ threads: {} });
    vi.clearAllMocks();
  });

  it("streams text, usage, and completion into a stable assistant turn", async () => {
    vi.mocked(api.chatStream).mockResolvedValue(makeResponse([
      'event: text\ndata: {"text":"Hello"}\n\n',
      'event: text\ndata: {"text":" there"}\n\n',
      'event: usage\ndata: {"input_tokens":3,"output_tokens":2,"cumulative_input":3,"cumulative_output":2}\n\n',
      'event: done\ndata: {"stop_reason":"end_turn"}\n\n',
    ]));

    await useChatStore.getState().send("thr_1", "Hi");

    const thread = useChatStore.getState().threads.thr_1;
    expect(thread.isStreaming).toBe(false);
    expect(thread.usage).toEqual({ cumulative_input: 3, cumulative_output: 2 });
    expect(thread.turns).toHaveLength(2);
    expect(thread.turns[1]).toMatchObject({
      role: "assistant",
      status: "done",
      stopReason: "end_turn",
    });
    expect(thread.turns[1].blocks[0]).toMatchObject({
      type: "text",
      text: "Hello there",
      streaming: false,
    });
  });

  it("revalidates panels after a state-mutating tool result", async () => {
    vi.mocked(api.chatStream).mockResolvedValue(makeResponse([
      'event: tool_call_start\ndata: {"id":"t1","name":"data_pipeline_run"}\n\n',
      'event: tool_result\ndata: {"id":"t1","name":"data_pipeline_run","result":{"kind":"data_pipeline_result","all_ok":true,"stages":[]}}\n\n',
      'event: done\ndata: {"stop_reason":"end_turn"}\n\n',
    ]));

    await useChatStore.getState().send("thr_rv", "run the pipeline");
    expect(revalidateData).toHaveBeenCalled();
  });

  it("revalidates via result kind when the name is empty (Claude Code MCP path)", async () => {
    // The claude-code provider forwards MCP tool results with an empty name,
    // so detection must fall back to the result kind.
    vi.mocked(api.chatStream).mockResolvedValue(makeResponse([
      'event: tool_result\ndata: {"id":"t3","name":"","result":{"kind":"config_edit_result","path":"configs/data.yaml"}}\n\n',
      'event: done\ndata: {"stop_reason":"end_turn"}\n\n',
    ]));

    await useChatStore.getState().send("thr_mcp", "change the split");
    expect(revalidateData).toHaveBeenCalled();
  });

  it("does not revalidate after a read-only tool result", async () => {
    vi.mocked(api.chatStream).mockResolvedValue(makeResponse([
      'event: tool_call_start\ndata: {"id":"t2","name":"dataset_audit"}\n\n',
      'event: tool_result\ndata: {"id":"t2","name":"dataset_audit","result":{"kind":"dataset_audit","warnings":[]}}\n\n',
      'event: done\ndata: {"stop_reason":"end_turn"}\n\n',
    ]));

    await useChatStore.getState().send("thr_ro", "audit my data");
    expect(revalidateData).not.toHaveBeenCalled();
  });

  it("turns provider setup failures into actionable chat errors", async () => {
    vi.mocked(api.chatStream).mockRejectedValue(
      new Error("AI chat failed (500 Internal Server Error): No providers configured."),
    );

    await useChatStore.getState().send("thr_2", "Can you help?");

    const thread = useChatStore.getState().threads.thr_2;
    expect(thread.isStreaming).toBe(false);
    expect(thread.turns[1].status).toBe("error");
    expect(thread.turns[1].blocks[0].text).toContain("No AI provider is configured");
  });

  it("rewinds server + local history before an edit-and-resend", async () => {
    const mkMsg = (idx: number, role: "user" | "assistant", text: string) => ({
      id: `msg_${idx}`,
      thread_id: "thr_4",
      idx,
      role,
      content: [{ type: "text" as const, text }],
      created_at: new Date().toISOString(),
    });
    useChatStore.getState().setFromStored("thr_4", [
      mkMsg(0, "user", "first question"),
      mkMsg(1, "assistant", "first answer"),
      mkMsg(2, "user", "second question"),
      mkMsg(3, "assistant", "second answer"),
    ]);

    vi.mocked(api.truncateThread).mockResolvedValue({ deleted: 2, thread_id: "thr_4" });
    vi.mocked(api.chatStream).mockResolvedValue(makeResponse([
      'event: text\ndata: {"text":"revised answer"}\n\n',
      'event: done\ndata: {"stop_reason":"end_turn"}\n\n',
    ]));

    await useChatStore.getState().send("thr_4", "edited question", {
      truncateFromIdx: 2,
    });

    expect(api.truncateThread).toHaveBeenCalledWith("thr_4", 2);
    const turns = useChatStore.getState().threads.thr_4.turns;
    expect(turns).toHaveLength(4);
    expect(turns[2]).toMatchObject({ role: "user" });
    expect(turns[2].blocks[0].text).toBe("edited question");
    expect(turns[3].blocks[0].text).toBe("revised answer");
  });

  it("surfaces a rewind failure without starting a stream", async () => {
    vi.mocked(api.truncateThread).mockRejectedValue(new Error("boom"));

    await useChatStore.getState().send("thr_5", "edited", { truncateFromIdx: 0 });

    expect(api.chatStream).not.toHaveBeenCalled();
    const turns = useChatStore.getState().threads.thr_5.turns;
    expect(turns[turns.length - 1]).toMatchObject({
      role: "assistant",
      status: "error",
    });
  });

  it("keeps a local stopped turn when the persisted snapshot is shorter", async () => {
    vi.mocked(api.chatStream).mockImplementation((_, init) => new Promise((_, reject) => {
      init?.signal?.addEventListener("abort", () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        reject(err);
      });
    }));

    const pending = useChatStore.getState().send("thr_3", "Stop this");
    useChatStore.getState().abort("thr_3");
    await pending;

    useChatStore.getState().setFromStored("thr_3", [{
      id: "msg_1",
      thread_id: "thr_3",
      idx: 0,
      role: "user",
      content: [{ type: "text", text: "Stop this" }],
      created_at: new Date().toISOString(),
    }]);

    const thread = useChatStore.getState().threads.thr_3;
    expect(thread.turns).toHaveLength(2);
    expect(thread.turns[1]).toMatchObject({ role: "assistant", status: "done" });
    expect(thread.turns[1].blocks[0].text).toBe("Stopped.");
  });
});
