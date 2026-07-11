"use client";
/**
 * Monitor: production health at a glance. Summary tiles + latency and
 * throughput time-series over recent traffic, with quality and drift surfaced
 * side by side (not buried in tabs) and the raw request log below.
 */
import * as React from "react";
import useSWR from "swr";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Activity, AlertTriangle, CheckCircle2, Clock, Cpu, Gauge, Hash } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { RequestLogPayload } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { SectionTabs } from "@/components/ui/SectionTabs";
import { Badge } from "@/components/ui/Badge";
import { AskAIButton } from "@/components/ai/AskAI";
import { cn } from "@/lib/cn";
import { useChartColors } from "@/lib/useChartColors";

type Rec = Record<string, unknown>;

function pct(nums: number[], p: number): number {
  if (nums.length === 0) return 0;
  const s = [...nums].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
}

export default function MonitorPage() {
  const c = useChartColors();
  const { data: log } = useSWR<RequestLogPayload>("monitor:requests",
    () => api.monitorRequests(100), { refreshInterval: 5_000 });
  const { data: quality } = useSWR("monitor:quality", () => api.monitorQuality());
  const { data: drift } = useSWR("monitor:drift", () => api.monitorDrift());

  const recent = (log?.recent ?? []) as Rec[];
  // Sort by real timestamp ascending so charts read left=oldest, right=newest
  // (the API order isn't guaranteed, so don't rely on a bare reverse).
  const points = [...recent]
    .map((r) => ({
      ts: r.ts ? new Date(String(r.ts)).getTime() : 0,
      label: r.ts ? new Date(String(r.ts)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "",
      latency: Number(r.latency_ms) || 0,
      inTok: Number(r.input_tokens) || 0,
      outTok: Number(r.output_tokens) || 0,
    }))
    .sort((a, b) => a.ts - b.ts)
    .map((p, i) => ({ ...p, i, label: p.label || String(i) }));
  const latencies = points.map((p) => p.latency);
  // NOTE for review: p50 has been observed far below the reported avg (e.g.
  // 0.2ms vs 7.3ms avg), which suggests a units/aggregation mismatch between
  // this client percentile and the backend's avg_latency_ms. Verify the source.
  const p50 = pct(latencies, 50);
  const p95 = pct(latencies, 95);
  const versions = Object.keys(log?.summary?.by_model_version ?? {});
  const backends = Array.from(new Set(recent.map((r) => String(r.backend ?? "?"))));

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-extrabold text-ink">Monitor</h1>
          <p className="text-sm text-ink-500 mt-1">
            Live health of the served model: latency, throughput, quality, and drift.
          </p>
        </div>
      </div>

      {log && !log.present ? (
        <Card><CardBody className="text-sm text-ink-500">
          No request traffic logged yet. Chat with the model in the Playground to
          generate requests, then watch them here.
        </CardBody></Card>
      ) : (
        <SectionTabs
          ariaLabel="Monitor sections"
          tabs={[
            { key: "overview", label: "Overview", icon: Activity },
            { key: "quality", label: "Quality & Drift", icon: Gauge },
            {
              key: "log", label: "Request log", icon: Hash,
              badge: <span className="ml-1 rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-ink-500">{log?.total ?? 0}</span>,
            },
          ]}
          panels={{
            overview: (
              <>
                {/* Summary tiles */}
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
                  <Tile icon={Hash} label="requests" value={String(log?.total ?? 0)} />
                  <Tile icon={Clock} label="avg latency" value={`${(log?.summary?.avg_latency_ms ?? 0).toFixed(1)} ms`} />
                  <Tile icon={Gauge} label="p50 latency" value={`${p50.toFixed(1)} ms`} />
                  <Tile icon={Gauge} label="p95 latency" value={`${p95.toFixed(1)} ms`}
                    tone={p95 > 3000 ? "warn" : "ink"} />
                  <Tile icon={Activity} label="output chars" value={(log?.summary?.total_output_chars ?? 0).toLocaleString()} />
                  <Tile icon={Cpu} label="model versions" value={String(versions.length || 1)} />
                </div>

                {/* Charts */}
                <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <ChartCard title="Latency over time" hint="per request, ms">
                    <ResponsiveContainer width="100%" height={200}>
                      <AreaChart data={points} margin={{ top: 5, right: 8, bottom: 0, left: -8 }}>
                        <defs>
                          <linearGradient id="lat" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={c.violet} stopOpacity={0.35} />
                            <stop offset="100%" stopColor={c.violet} stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke={c.grid} />
                        <XAxis dataKey="label" tick={{ fontSize: 9, fill: c.tick }} minTickGap={40} />
                        <YAxis tick={{ fontSize: 9, fill: c.tick }} width={38} />
                        <Tooltip contentStyle={{ fontSize: 11, borderRadius: 4, background: c.tooltipBg, color: c.tooltipFg, border: "none" }} />
                        {/* Violet (a distinct categorical hue) so latency isn't
                            confused with the blue input-token bars beside it.
                            linear + visible dots: latency is discrete per-request
                            samples, not continuous traffic — don't imply a stream. */}
                        <Area type="linear" dataKey="latency" stroke={c.violet} fill="url(#lat)"
                          strokeWidth={2} dot={{ r: 2, fill: c.violet, strokeWidth: 0 }}
                          activeDot={{ r: 4 }} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </ChartCard>
                  <ChartCard title="Token throughput" hint="input vs output tokens per request">
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={points} margin={{ top: 5, right: 8, bottom: 0, left: -8 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={c.grid} />
                        <XAxis dataKey="label" tick={{ fontSize: 9, fill: c.tick }} minTickGap={40} />
                        <YAxis tick={{ fontSize: 9, fill: c.tick }} width={38} />
                        <Tooltip contentStyle={{ fontSize: 11, borderRadius: 4, background: c.tooltipBg, color: c.tooltipFg, border: "none" }} />
                        <Legend wrapperStyle={{ fontSize: 10 }} iconType="square" iconSize={8} />
                        <Bar dataKey="inTok" name="input" stackId="t" fill={c.accent} />
                        <Bar dataKey="outTok" name="output" stackId="t" fill={c.teal} />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartCard>
                </div>

                {/* At-a-glance quality & drift so the overview doesn't bottom
                    out into empty space; the full reports live in the next tab. */}
                <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {([
                    { title: "Response quality", d: quality },
                    { title: "Drift", d: drift },
                  ] as const).map(({ title, d }) => (
                    <div key={title} className="rounded-xl border border-ink-200 bg-card p-3.5">
                      <div className="flex items-center gap-2 text-sm font-bold text-ink">
                        {title}
                        <Badge tone={d?.present ? "ok" : "muted"} className="ml-auto">
                          {d?.present ? <><CheckCircle2 size={11} /> ready</> : "not run"}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-ink-500">
                        {d?.present
                          ? "Report ready — open the Quality & Drift tab for the full breakdown."
                          : "Not run yet on recent traffic."}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            ),
            quality: (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <ReportCard title="Response quality" present={quality?.present ?? false}
                  report={quality?.report as Rec | undefined}
                  prompt="Run the quality monitor on recent traffic and summarize the report." />
                <ReportCard title="Drift" present={drift?.present ?? false}
                  report={drift?.report as Rec | undefined}
                  prompt="Run the drift monitor comparing production prompts to the training distribution, and summarize the report." />
              </div>
            ),
            log: (
              <Card>
                <CardHeader className="flex items-center gap-2 text-sm font-bold">
                  Request log
                  <span className="font-normal text-[11px] text-ink-500">{log?.total ?? 0} total</span>
                  {backends.length ? (
                    <span className="ml-auto flex gap-1">
                      {backends.map((b) => <Badge key={b} tone="muted">{b}</Badge>)}
                    </span>
                  ) : null}
                </CardHeader>
                <CardBody className="overflow-x-auto p-0">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-ink-100 text-left text-[10px] uppercase tracking-wider text-ink-400">
                        <th className="px-4 py-2">time</th>
                        <th className="px-2 py-2">model</th>
                        <th className="px-2 py-2">backend</th>
                        <th className="px-2 py-2 text-right">in tok</th>
                        <th className="px-2 py-2 text-right">out tok</th>
                        <th className="px-4 py-2 text-right">latency</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-50">
                      {recent.slice(0, 25).map((r, i) => (
                        <tr key={i} className="hover:bg-ink-50/50">
                          <td className="px-4 py-1.5 text-ink-500">{r.ts ? new Date(String(r.ts)).toLocaleString() : "—"}</td>
                          <td className="px-2 py-1.5 font-medium text-ink">{String(r.model ?? "—")}<span className="text-ink-400"> v{String(r.model_version ?? "?")}</span></td>
                          <td className="px-2 py-1.5 text-ink-500">{String(r.backend ?? "—")}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-ink-600">{String(r.input_tokens ?? "—")}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-ink-600">{String(r.output_tokens ?? "—")}</td>
                          <td className="px-4 py-1.5 text-right tabular-nums text-ink">{Number(r.latency_ms ?? 0).toFixed(1)} ms</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardBody>
              </Card>
            ),
          }}
        />
      )}
    </div>
  );
}

function Tile({ icon: Icon, label, value, tone }: {
  icon: typeof Gauge; label: string; value: string; tone?: "ink" | "warn";
}) {
  return (
    <div className="rounded-xl border border-ink-200 bg-card p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-400">
        <Icon size={12} /> {label}
      </div>
      <div className={cn("mt-1 text-xl font-extrabold tabular-nums",
        tone === "warn" ? "text-amber-700" : "text-ink")}>{value}</div>
    </div>
  );
}

function ChartCard({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="flex items-baseline gap-2 text-sm font-bold">
        {title} <span className="font-normal text-[11px] text-ink-500">{hint}</span>
      </CardHeader>
      <CardBody>{children}</CardBody>
    </Card>
  );
}

function ReportCard({ title, present, report, prompt }: {
  title: string; present: boolean; report: Rec | undefined; prompt: string;
}) {
  const entries = Object.entries(report ?? {}).filter(
    ([, v]) => typeof v === "number" || typeof v === "string" || typeof v === "boolean");
  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        {title}
        <Badge tone={present ? "ok" : "muted"} className="ml-auto">
          {present ? <><CheckCircle2 size={11} /> ready</> : "not run"}
        </Badge>
      </CardHeader>
      <CardBody className="text-xs">
        {!present ? (
          <div className="flex items-center gap-2 text-ink-500">
            <AlertTriangle size={13} className="text-amber-500" />
            Not run yet.
            <AskAIButton prompt={prompt}>Run it</AskAIButton>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {entries.slice(0, 8).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-ink-50 px-2 py-1.5">
                <div className="text-[10px] uppercase tracking-wider text-ink-400">{k.replace(/_/g, " ")}</div>
                <div className="font-semibold tabular-nums text-ink">{String(v)}</div>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
