"use client";
/**
 * Dashboard: the project command center. State-aware and dense but scannable —
 * pipeline + next action up top, live metrics that link where they came from,
 * the latest run at a glance, and one-click actions (smoke train, evals, serve)
 * for people who don't want to click through five pages to do one thing.
 */
import * as React from "react";
import useSWR from "swr";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Cpu, Database, FlaskConical, Gauge, Lock, Play, Radio, Rocket, ScrollText, ShieldCheck, Sparkles, XCircle, Zap } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { EvalRunResult, GateResult } from "@/lib/api";
import { ProjectStatusCard } from "@/components/artifacts/ProjectStatusCard";
import { LiveTrainingCard } from "@/components/artifacts/LiveTrainingCard";
import { LossCurve } from "@/components/artifacts/LossCurve";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useLiveTraining } from "@/lib/hooks/useLiveTraining";
import { useUiStore } from "@/lib/stores/uiStore";
import { fmtDuration, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/cn";

type Metrics = Record<string, number | undefined>;

export default function DashboardPage() {
  const { data: stateData } = useSWR("state", () => api.state(), { refreshInterval: 5_000 });
  const live = useLiveTraining();
  const { data: runsData, mutate: mutateRuns } = useSWR("runs-metrics",
    () => api.runs(true), { refreshInterval: 8_000 });
  const { data: evalData, mutate: mutateEval } = useSWR("eval", () => api.evalMetrics());
  const { data: gate, mutate: mutateGate } = useSWR("eval-gate-report", () => api.evalGateReport());
  const { data: registry } = useSWR("registry", () => api.registry());
  const { data: serving, mutate: mutateServing } = useSWR("serving:status",
    () => api.servingStatus(), { refreshInterval: 5_000 });
  const { data: brief } = useSWR("brief", () => api.getBrief());
  const { data: caps } = useSWR("capabilities", () => api.capabilities());
  const { data: files } = useSWR("data:files", () => api.listDataFiles());

  const status = stateData?.status;
  const metrics = (evalData?.metrics ?? {}) as Metrics;
  const runs = runsData?.runs ?? [];
  const lastRun = runs.find((r) => r.status !== "running") ?? runs[0];
  const models = registry?.models ?? [];
  const dangerous = caps?.dangerous_enabled ?? true;
  const goal = (brief?.fields?.goal || brief?.fields?.title || "").trim();

  // Where each alias points, across all models.
  const aliasVersion = (alias: string) => {
    for (const m of models) {
      const v = m.aliases?.[alias];
      if (v) return `${m.name} v${v}`;
    }
    return null;
  };
  const deployed = aliasVersion("production") ?? aliasVersion("staging");

  const processed = (files?.files ?? []).filter((f) => f.kind === "processed");
  const splitCount = (name: string) =>
    processed.find((f) => f.name === `${name}.jsonl`)?.line_count ?? 0;

  const gateVerdict: "pass" | "fail" | "none" =
    gate?.present ? (gate.passed ? "pass" : "fail") : "none";

  const refreshEval = () => { void mutateEval(); void mutateGate(); };

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-5">
      {/* ---- Header + goal + quick actions ---- */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold text-ink">Dashboard</h1>
          {goal ? (
            <p className="mt-1 max-w-2xl text-sm text-ink-600">
              <span className="font-semibold text-ink-500">Goal:</span> {goal}{" "}
              <Link href="/overview" className="text-accent-600 hover:underline">edit</Link>
            </p>
          ) : (
            <p className="mt-1 text-sm text-ink-500">
              No project goal yet.{" "}
              <Link href="/overview" className="font-semibold text-accent-600 hover:underline">
                Write a brief →
              </Link>{" "}so every page (and the AI) works toward it.
            </p>
          )}
        </div>
      </div>

      <QuickActions
        dangerous={dangerous}
        serving={serving?.running ?? false}
        onTrained={() => void mutateRuns()}
        onEvaluated={refreshEval}
        onServed={() => void mutateServing()}
      />

      {/* ---- Pipeline + next action + hardware ---- */}
      {status ? <ProjectStatusCard data={status} /> : null}

      {/* ---- Live training ---- */}
      {live?.active ? (
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">Live</div>
          <LiveTrainingCard data={live} />
        </div>
      ) : null}

      {/* ---- Metrics tiles ---- */}
      {/* Gate + Serving live in the side cards below (with their why + action),
          so the KPI strip stays complementary: measured numbers only, no
          duplicate status. */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricTile href="/evaluate" icon={Gauge} label="task score"
          value={metrics.task_score != null ? Number(metrics.task_score).toFixed(3) : "not run"}
          tone={metrics.task_score != null ? "ink" : "muted"} />
        <MetricTile href="/evaluate" icon={FlaskConical} label="safety crit/high"
          value={metrics.task_score != null
            ? `${metrics.safety_failures_critical ?? 0}/${metrics.safety_failures_high ?? 0}`
            : "not run"}
          tone={metrics.task_score == null ? "muted"
            : (metrics.safety_failures_critical ?? 0) > 0 ? "fail"
            : (metrics.safety_failures_high ?? 0) > 0 ? "warn" : "ok"} />
        <MetricTile href="/runs" icon={Zap} label="last run loss"
          value={lastRun?.final_loss != null ? lastRun.final_loss.toFixed(3) : "no runs"}
          tone={lastRun ? "ink" : "muted"} />
        <MetricTile href="/deploy" icon={Rocket} label="deployed"
          value={deployed ?? "none"} tone={deployed ? "ok" : "muted"} small />
      </div>

      {/* ---- Latest run (with serving + data beneath) | gate rail ---- */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <LatestRun run={lastRun} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <ServingPanel serving={serving} />
            <DataPanel train={splitCount("train")} evalN={splitCount("eval")}
              test={splitCount("test")} />
          </div>
        </div>
        <div className="space-y-4">
          <GatePanel verdict={gateVerdict} gate={gate} onRun={refreshEval} />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------ Quick actions ------------------------------ */
function QuickActions({
  dangerous, serving, onTrained, onEvaluated, onServed,
}: {
  dangerous: boolean;
  serving: boolean;
  onTrained: () => void;
  onEvaluated: () => void;
  onServed: () => void;
}) {
  const openDrawer = useUiStore((s) => s.openDrawer);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [msg, setMsg] = React.useState<{ tone: "ok" | "fail"; text: string } | null>(null);

  const flash = (tone: "ok" | "fail", text: string) => {
    setMsg({ tone, text });
    window.setTimeout(() => setMsg(null), 5_000);
  };

  const smoke = async () => {
    setBusy("train");
    try {
      const r = await api.trainLaunch({ method: "sft", smoke: true });
      const l = r.launch;
      if (l.kind === "error") flash("fail", l.message ?? "Launch blocked.");
      else { flash("ok", `Smoke train started (PID ${l.pid}).`); onTrained(); }
    } catch (e) { flash("fail", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const evals = async () => {
    setBusy("eval");
    try {
      const r = await api.evalRun({}) as EvalRunResult | { kind: "error"; message: string };
      if (r.kind === "error") { flash("fail", r.message); return; }
      const g = await api.evalGate() as GateResult | { kind: "error"; message: string };
      if (g.kind === "error") flash("fail", g.message);
      else flash(g.passed ? "ok" : "fail", g.passed ? "Evals ran: gate PASSED." : "Evals ran: gate failed.");
      onEvaluated();
    } catch (e) { flash("fail", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const serve = async () => {
    setBusy("serve");
    try {
      const r = await api.servingStart({ backend: "transformers" });
      if (r.kind === "serving_status") { flash("ok", "Serving started."); onServed(); }
      else flash("fail", "Couldn't start serving.");
    } catch (e) { flash("fail", e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  return (
    <Card>
      <CardBody className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-ink-500">
          Quick actions
        </span>
        <Button size="sm" variant="primary" onClick={() => void smoke()}
          disabled={!dangerous || busy !== null}>
          {busy === "train" ? <Spin /> : <Zap size={13} />} Smoke train
        </Button>
        <Button size="sm" variant="secondary" onClick={() => void evals()}
          disabled={!dangerous || busy !== null}>
          {busy === "eval" ? <Spin /> : <FlaskConical size={13} />} Run evals + gate
        </Button>
        <Button size="sm" variant="secondary" onClick={() => void serve()}
          disabled={!dangerous || busy !== null || serving}>
          {busy === "serve" ? <Spin /> : <Radio size={13} />} {serving ? "Serving" : "Serve model"}
        </Button>
        <Button size="sm" variant="ghost"
          onClick={() => openDrawer("Look at my project state and tell me the single highest-impact thing to do next, then offer to do it.")}>
          <Sparkles size={13} className="text-coral" /> Ask Copilot
        </Button>
        {msg ? (
          <span className={cn("ml-auto inline-flex items-center gap-1 text-[11px] font-semibold",
            msg.tone === "ok" ? "text-emerald-700" : "text-red-700")}>
            {msg.tone === "ok" ? <CheckCircle2 size={12} /> : <XCircle size={12} />} {msg.text}
          </span>
        ) : !dangerous ? (
          <span className="ml-auto text-warn"
            title="Actions are locked: restart the backend with PUFFIN_COPILOT_ENABLE_DANGEROUS=1 to enable them">
            <Lock size={13} />
          </span>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Spin() {
  return <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

/* ------------------------------ Metric tile ------------------------------ */
function MetricTile({
  href, icon: Icon, label, value, tone, small,
}: {
  href: string;
  icon: typeof Gauge;
  label: string;
  value: string;
  tone: "ok" | "fail" | "warn" | "ink" | "muted";
  small?: boolean;
}) {
  const color = tone === "ok" ? "text-emerald-700" : tone === "fail" ? "text-red-700"
    : tone === "warn" ? "text-amber-700" : tone === "muted" ? "text-ink-400" : "text-ink";
  // A failing tile must not read as just another neutral KPI: give it the
  // coral second-ink as a wash + left stripe so the eye lands on it first.
  const alert = tone === "fail";
  return (
    <Link href={href}
      className={cn(
        "group rounded-xl border p-3 transition-colors hover:border-accent hover:shadow-glow",
        alert ? "border-fail/50 border-l-[3px] border-l-fail bg-fail/[0.06]"
          : tone === "muted" ? "border-ink-200/70 bg-card/50"
          : "border-ink-200 bg-card",
      )}>
      <div className={cn("flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider",
        alert ? "text-red-700/80" : "text-ink-400")}>
        <Icon size={12} /> {label}
      </div>
      <div className={cn("mt-1 font-extrabold tabular-nums", small ? "text-sm" : "text-2xl", color)}>
        {value}
      </div>
    </Link>
  );
}

/* ------------------------------ Latest run ------------------------------ */
function LatestRun({ run }: { run: import("@/lib/types").TrainingRun | undefined }) {
  if (!run) {
    return (
      <Card>
        <CardHeader className="text-sm font-bold">Latest run</CardHeader>
        <CardBody className="flex flex-col items-start justify-center gap-3 py-10 text-sm text-ink-500">
          No training runs yet. Kick off a quick smoke test to prove the pipeline,
          then go full.
          <Link href="/train"
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink-50 hover:bg-accent-600">
            <Play size={13} /> Open Train studio <ArrowRight size={13} />
          </Link>
        </CardBody>
      </Card>
    );
  }
  const failed = run.status === "failed" || run.status === "stalled";
  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold text-ink">Latest run</span>
        <span className="text-xs text-ink-500">{run.run_name}</span>
        <Badge tone={failed ? "fail" : run.status === "completed" ? "ok" : "info"}>{run.status}</Badge>
        {run.smoke_test ? <Badge tone="info">smoke</Badge> : null}
        <span className="ml-auto text-[11px] text-ink-400">{fmtRelative(run.end_ts ?? run.start_ts)}</span>
      </CardHeader>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-600">
          <span>final loss <b className="tabular-nums text-ink">{run.final_loss?.toFixed(4) ?? "n/a"}</b></span>
          <span>best eval <b className="tabular-nums text-ink">{run.best_eval_loss?.toFixed(4) ?? "not run"}</b></span>
          <span>duration <b className="tabular-nums text-ink">{fmtDuration(run.duration_s)}</b></span>
          <span>steps <b className="tabular-nums text-ink">{(run.total_steps ?? 0).toLocaleString()}</b></span>
          <span className="text-ink-500">{run.method.toUpperCase()} · {run.base_model}</span>
        </div>
        {(run.metrics?.length ?? 0) > 1 ? (
          <LossCurve rows={run.metrics ?? []} height={180} />
        ) : (
          <div className="rounded-lg bg-ink-50 py-6 text-center text-xs text-ink-400">
            No loss history for this run.
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/runs" className="inline-flex items-center gap-1 text-xs font-semibold text-accent-600 hover:underline">
            <ScrollText size={12} /> Run details & logs
          </Link>
          {run.status === "completed" && !run.smoke_test ? (
            <Link href="/evaluate" className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-accent-600">
              <FlaskConical size={12} /> Evaluate
            </Link>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

/* ------------------------------ Side panels ------------------------------ */
function GatePanel({
  verdict, gate, onRun,
}: {
  verdict: "pass" | "fail" | "none";
  gate: { failures?: string[] } | undefined;
  onRun: () => void;
}) {
  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        <ShieldCheck size={14} className="text-amber-600" /> Promotion gate
        <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold uppercase",
          verdict === "pass" ? "bg-emerald-50 text-emerald-700"
            : verdict === "fail" ? "bg-red-50 text-red-700" : "bg-ink-100 text-ink-500")}>
          {verdict === "none" ? "not run" : verdict}
        </span>
      </CardHeader>
      <CardBody className="text-xs text-ink-600">
        {verdict === "none" ? (
          <>Run the evals to check whether the model is promotable.</>
        ) : verdict === "pass" ? (
          <>All thresholds met. The latest adapter is safe to push and promote.</>
        ) : (
          <>Failing: <span className="font-semibold text-red-700">{(gate?.failures ?? []).join(", ") || "see Evaluate"}</span>.</>
        )}
        <div className="mt-2">
          <Link href="/evaluate" className="text-[11px] font-semibold text-accent-600 hover:underline">
            Open Evaluate →
          </Link>
        </div>
      </CardBody>
    </Card>
  );
}

function ServingPanel({ serving }: { serving: { running?: boolean; backend?: string; url?: string } | undefined }) {
  const running = serving?.running ?? false;
  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        <Radio size={14} className="text-amber-600" /> Serving
        <Badge tone={running ? "ok" : "muted"} className="ml-auto">{running ? "live" : "stopped"}</Badge>
      </CardHeader>
      <CardBody className="text-xs text-ink-600">
        {running ? (
          <>Serving <b>{serving?.backend}</b> at <code>{serving?.url}</code>.</>
        ) : (
          <>Nothing is serving. Start it from the quick actions or Deploy.</>
        )}
        <div className="mt-2 flex gap-3">
          <Link href="/playground" className="text-[11px] font-semibold text-accent-600 hover:underline">Playground →</Link>
          <Link href="/deploy" className="text-[11px] font-semibold text-accent-600 hover:underline">Deploy →</Link>
        </div>
      </CardBody>
    </Card>
  );
}

function DataPanel({ train, evalN, test }: { train: number; evalN: number; test: number }) {
  const ready = train > 0;
  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        <Database size={14} className="text-amber-600" /> Data
        <Badge tone={ready ? "ok" : "warn"} className="ml-auto">{ready ? "splits ready" : "not built"}</Badge>
      </CardHeader>
      <CardBody className="text-xs text-ink-600">
        <div className="flex gap-4">
          <span>train <b className="tabular-nums text-ink">{train.toLocaleString()}</b></span>
          <span>eval <b className="tabular-nums text-ink">{evalN.toLocaleString()}</b></span>
          <span>test <b className="tabular-nums text-ink">{test.toLocaleString()}</b></span>
        </div>
        <div className="mt-2">
          <Link href="/data" className="text-[11px] font-semibold text-accent-600 hover:underline">Open Data →</Link>
        </div>
      </CardBody>
    </Card>
  );
}
