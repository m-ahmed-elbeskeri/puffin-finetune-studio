"use client";
/**
 * Playground: a real chat against the served model. Multi-turn conversation on
 * the right, controls (serving, system prompt, sampling params, samples) on the
 * left. Everything is proxied through the backend so there's no CORS to :8089.
 */
import * as React from "react";
import useSWR from "swr";
import { AlertTriangle, Eraser, Loader2, Send, User, Zap } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ServeControl } from "@/components/serve/ServeControl";
import { PuffinMark } from "@/components/chat/PuffinMark";
import { cn } from "@/lib/cn";

const URL = "http://127.0.0.1:8089";

interface Msg { role: "user" | "assistant"; content: string; latency?: number; tokens?: number }

export default function PlaygroundPage() {
  const { data: health } = useSWR("serving:health",
    () => api.servingHealth(URL), { refreshInterval: 4_000 });
  const [system, setSystem] = React.useState("You are a helpful assistant.");
  const [temperature, setTemperature] = React.useState(0.7);
  const [maxTokens, setMaxTokens] = React.useState(256);
  const [messages, setMessages] = React.useState<Msg[]>([]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const up = health?.up ?? false;

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy]);

  const send = async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    const convo: Msg[] = [...messages, { role: "user", content: t }];
    setMessages(convo);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const wire = [
        ...(system.trim() ? [{ role: "system", content: system.trim() }] : []),
        ...convo.map((m) => ({ role: m.role, content: m.content })),
      ];
      const r = await api.serveChat({ url: URL, messages: wire, temperature, max_tokens: maxTokens });
      if (r.kind === "error") { setError(r.message); return; }
      setMessages([...convo, {
        role: "assistant", content: r.text, latency: r.latency_ms,
        tokens: (r.usage as { completion_tokens?: number })?.completion_tokens,
      }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-ink-200 bg-card/70 px-6 py-3">
        <h1 className="text-xl font-extrabold text-ink">Playground</h1>
        <p className="text-[13px] text-ink-500">
          Multi-turn chat against your served model — the same serving code as production.
        </p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[330px_1fr]">
        {/* ---- Controls ---- */}
        <div className="space-y-4 overflow-y-auto">
          <ServeControl showPlaygroundLink={false} />

          <Card>
            <CardHeader className="text-sm font-bold">Parameters</CardHeader>
            <CardBody className="space-y-3">
              <label className="block space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-ink-500">System prompt</span>
                <textarea value={system} onChange={(e) => setSystem(e.target.value)} rows={3}
                  className="w-full resize-y rounded-lg border border-ink-200 px-2.5 py-1.5 text-xs
                             focus:border-accent focus:outline-none" />
              </label>
              <label className="block space-y-1">
                <span className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-ink-500">
                  Temperature <span className="tabular-nums text-ink-600">{temperature.toFixed(2)}</span>
                </span>
                <input type="range" min={0} max={2} step={0.05} value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full accent-amber-500" />
                <span className="text-[10px] text-ink-400">Lower = focused, higher = creative.</span>
              </label>
              <label className="block space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-ink-500">Max new tokens</span>
                <input type="number" min={1} max={4096} value={maxTokens}
                  onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 256)}
                  className="w-full rounded-lg border border-ink-200 px-2.5 py-1.5 text-sm
                             focus:border-accent focus:outline-none" />
              </label>
            </CardBody>
          </Card>
        </div>

        {/* ---- Conversation ---- */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-ink-200 bg-card">
          <div className="flex items-center gap-2 border-b border-ink-100 px-4 py-2 text-xs">
            <span className={cn("inline-flex items-center gap-1.5 font-semibold",
              up ? "text-emerald-700" : "text-amber-700")}>
              <span className={cn("h-1.5 w-1.5 rounded-full", up ? "bg-emerald-500" : "bg-amber-500")} />
              {up ? "serving live" : "not serving"}
            </span>
            <span className="text-ink-400">· {messages.filter((m) => m.role === "user").length} turns</span>
            {messages.length > 0 ? (
              <button type="button" onClick={() => { setMessages([]); setError(null); }}
                className="ml-auto inline-flex items-center gap-1 text-[11px] font-semibold text-ink-500 hover:text-ink">
                <Eraser size={12} /> Clear
              </button>
            ) : null}
          </div>

          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-ink-400">
                <PuffinMark size={40} />
                {up ? "Say something to your model." : "Start serving on the left, then chat."}
              </div>
            ) : messages.map((m, i) => <Bubble key={i} msg={m} />)}
            {busy ? (
              <div className="flex items-center gap-2 text-xs text-ink-400">
                <Loader2 size={13} className="animate-spin" /> generating…
              </div>
            ) : null}
            {error ? (
              <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {error}
                {!up ? <span className="block">Is the model finished loading? Check the serving log.</span> : null}
              </div>
            ) : null}
          </div>

          <div className="border-t border-ink-200 p-3">
            <div className="flex items-end gap-2 rounded-xl border border-ink-200 bg-card p-1.5 focus-within:border-accent">
              <textarea
                value={input} onChange={(e) => setInput(e.target.value)} rows={1}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); }
                }}
                placeholder="Message the model… (Enter to send)"
                className="max-h-40 min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm
                           placeholder:text-ink-400 focus:outline-none" />
              <Button size="sm" variant="primary" onClick={() => void send(input)}
                disabled={busy || !input.trim()}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bubble({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex gap-2", isUser ? "flex-row-reverse" : "")}>
      <span className={cn(
        "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
        isUser ? "bg-ink-100 text-ink-600" : "bg-amber-50",
      )}>
        {isUser ? <User size={15} /> : <PuffinMark size={26} />}
      </span>
      <div className={cn("min-w-0 max-w-[80%] space-y-1", isUser ? "items-end text-right" : "")}>
        <div className={cn(
          "whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm leading-relaxed",
          isUser ? "bg-accent/15 text-ink" : "border border-ink-200 bg-card text-ink",
        )}>
          {msg.content}
        </div>
        {!isUser && (msg.latency != null || msg.tokens != null) ? (
          <div className="flex items-center gap-2 px-1 text-[10px] text-ink-400">
            {msg.latency != null ? <span className="inline-flex items-center gap-0.5"><Zap size={9} /> {msg.latency} ms</span> : null}
            {msg.tokens != null ? <span>{msg.tokens} tok</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
