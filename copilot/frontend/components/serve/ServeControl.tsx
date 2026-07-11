"use client";
/**
 * Start / stop the local serving server from the UI, on :8089 where the
 * Playground and health checks look. The transformers backend loads the real
 * model + adapter (give it a moment); vllm uses the vLLM engine.
 */
import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ArrowRight, Loader2, Lock, Play, Radio, ScrollText, Square } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { ServingLogPayload } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LockedNote } from "@/components/ui/LockedNote";
import { cn } from "@/lib/cn";

export function ServeControl({ showPlaygroundLink = true }: { showPlaygroundLink?: boolean }) {
  const { data: status, mutate } = useSWR("serving:status",
    () => api.servingStatus(), { refreshInterval: 4_000 });
  const { data: health } = useSWR("serving:health",
    () => api.servingHealth(), { refreshInterval: 4_000 });
  const { data: caps } = useSWR("capabilities", () => api.capabilities());

  const dangerous = caps?.dangerous_enabled ?? true;
  const running = status?.running ?? false;
  const responding = health?.up ?? false;

  const [backend, setBackend] = React.useState<"transformers" | "vllm">("transformers");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const start = async () => {
    setBusy(true); setErr(null);
    try { await api.servingStart({ backend }); await mutate(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true); setErr(null);
    try { await api.servingStop(); await mutate(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        <Radio size={14} className="text-amber-600" /> Serve the model
        {running ? (
          <Badge tone={responding ? "ok" : "warn"}>
            <span className={cn("h-1.5 w-1.5 rounded-full",
              responding ? "bg-emerald-500 animate-pulseDot" : "bg-amber-500")} />
            {responding ? "live" : "starting"}
          </Badge>
        ) : (
          <Badge tone="muted">stopped</Badge>
        )}
      </CardHeader>
      <CardBody className="space-y-3">
        {running ? (
          <div className="text-xs text-ink-600">
            Serving <b>{status?.backend}</b> on <code>{status?.url}</code>
            {status?.pid ? <> · PID {status.pid}</> : null}.
            {" "}
            {responding
              ? "The server is responding."
              : "Waiting for the server to come up (the model may still be loading)."}
          </div>
        ) : (
          <div className="text-xs text-ink-500">
            Launches <code>llmops.serving.app</code> on <code>:8089</code> from
            your <code>configs/deploy.yaml</code>.
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-ink-500">Backend</span>
            <div className="flex items-center gap-1 rounded-lg border border-ink-200 p-0.5 text-[11px]">
              {(["transformers", "vllm"] as const).map((b) => (
                <button key={b} type="button" onClick={() => setBackend(b)}
                  className={cn(
                    "rounded-md px-2 py-1 font-semibold transition-colors",
                    backend === b ? "bg-accent text-ink" : "text-ink-500 hover:text-ink",
                  )}>
                  {b}
                </button>
              ))}
            </div>
          </div>
          {!running ? (
            <Button variant="primary" size="sm" onClick={() => void start()}
              disabled={busy || !dangerous}
              title={!dangerous ? "Locked: enable state-changing tools to serve" : undefined}>
              {busy ? <Loader2 size={13} className="animate-spin" />
                : !dangerous ? <Lock size={13} /> : <Play size={13} />}
              {!dangerous ? "Serving locked" : "Start serving"}
            </Button>
          ) : (
            <>
              {/* Start doubles as restart, so switching backend is one click. */}
              {backend !== status?.backend ? (
                <Button variant="primary" size="sm" onClick={() => void start()} disabled={busy}>
                  {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                  Switch to {backend}
                </Button>
              ) : null}
              <Button variant="danger" size="sm" onClick={() => void stop()} disabled={busy}>
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                Stop
              </Button>
              {showPlaygroundLink ? (
                <Link href="/playground"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5
                             text-xs font-semibold text-white transition-colors hover:bg-accent-600">
                  Chat in Playground <ArrowRight size={13} />
                </Link>
              ) : null}
            </>
          )}
        </div>

        <p className="text-[11px] text-ink-400">
          {!running
            ? (backend === "vllm"
                ? "vllm: high-throughput serving via the vLLM engine (needs the vLLM image / GPU)."
                : "transformers: loads the real base model + your adapter. Give it a moment to start.")
            : null}
        </p>

        {!dangerous ? <LockedNote action="Serving" /> : null}
        {err ? (
          <p className="flex items-start gap-1.5 text-[11px] text-red-700">
            <AlertTriangle size={11} className="mt-0.5 shrink-0" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{err}</span>
          </p>
        ) : null}

        <ServingLog live={running && !responding} />
      </CardBody>
    </Card>
  );
}

/** Collapsible tail of the serving process log (model-load progress + errors). */
function ServingLog({ live }: { live: boolean }) {
  const [open, setOpen] = React.useState(false);
  const { data } = useSWR<ServingLogPayload>(
    open ? "serving:log" : null, () => api.servingLog(400),
    { refreshInterval: open && live ? 3_000 : 0 });
  const preRef = React.useRef<HTMLPreElement>(null);
  React.useEffect(() => {
    if (live && preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight;
  }, [data, live]);

  return (
    <div className="rounded-lg border border-ink-200">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-bold
                   uppercase tracking-wider text-ink-500 hover:text-ink">
        <ScrollText size={13} className={open ? "text-accent-600" : "text-ink-400"} />
        Serving log
        {data?.present && typeof data.total_lines === "number" ? (
          <span className="font-normal normal-case tracking-normal text-ink-400">
            {data.total_lines.toLocaleString()} lines
          </span>
        ) : null}
        <span className="ml-auto text-[10px] font-semibold text-accent-600">
          {open ? "hide" : "view"}
        </span>
      </button>
      {open ? (
        <div className="border-t border-ink-100 p-2">
          {!data ? (
            <div className="px-2 py-3 text-[11px] text-ink-400">Reading log…</div>
          ) : !data.present ? (
            <div className="px-2 py-3 text-[11px] text-ink-400">
              {data.message ?? "No serving log yet."}
            </div>
          ) : (
            <pre ref={preRef}
              className="max-h-80 overflow-auto rounded-md bg-[#0f172a] p-2.5 font-mono
                         text-[10px] leading-relaxed text-slate-100">
              {data.lines.map((ln, i) => (
                <div key={i} className={cn(
                  /\b(error|traceback|exception|failed|oom|cuda out of memory)\b/i.test(ln)
                    ? "text-red-300"
                    : /\b(warn|warning)\b/i.test(ln) ? "text-amber-300" : "")}>
                  {ln || " "}
                </div>
              ))}
            </pre>
          )}
        </div>
      ) : null}
    </div>
  );
}
