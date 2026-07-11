"use client";
/**
 * Evaluation studio: author the eval sets that gate promotion, run them
 * against the latest adapter, and read the gate verdict. The eval sets are
 * NOT training data; they judge the trained model.
 */
import * as React from "react";
import useSWR from "swr";
import { AlertTriangle, CheckCircle2, FlaskConical, Loader2, Pencil, Play, ShieldCheck, XCircle } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { EvalRunResult, GateResult } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { LockedNote } from "@/components/ui/LockedNote";
import { Stat } from "@/components/ui/Stat";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EvalSets } from "@/components/eval/EvalSets";
import { StepWizard, WizardSection, type WizardStepDef } from "@/components/layout/StepWizard";
import { cn } from "@/lib/cn";

type Metrics = Record<string, number | undefined>;

export default function EvaluatePage() {
  const { data: metricsData, mutate: mutateMetrics } = useSWR("eval", () => api.evalMetrics());
  const { data: config, mutate: mutateConfig } = useSWR("eval-config", () => api.evalConfig());
  const { data: caps } = useSWR("capabilities", () => api.capabilities());

  const metrics = (metricsData?.metrics ?? {}) as Metrics;
  const gates = config?.gates ?? {};
  const dangerous = caps?.dangerous_enabled ?? true;

  const [running, setRunning] = React.useState(false);
  const [runResult, setRunResult] = React.useState<EvalRunResult | null>(null);
  const [gate, setGate] = React.useState<GateResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Editing the gate thresholds (configs/eval.yaml).
  const [editingGates, setEditingGates] = React.useState(false);
  const [draftGates, setDraftGates] = React.useState<Record<string, number>>({});
  const [savingGates, setSavingGates] = React.useState(false);
  const [gateErr, setGateErr] = React.useState<string | null>(null);
  const startEditGates = () => {
    setDraftGates({ ...(gates as Record<string, number>) });
    setGateErr(null); setEditingGates(true);
  };
  const saveGates = async () => {
    setSavingGates(true); setGateErr(null);
    try {
      await api.updateEvalGates(draftGates);
      await mutateConfig();
      setEditingGates(false);
    } catch (e) {
      setGateErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingGates(false);
    }
  };

  const runAll = async () => {
    setRunning(true); setError(null); setRunResult(null); setGate(null);
    try {
      const r = await api.evalRun({ backend: "transformers" });
      if (r.kind === "error") { setError(r.message); return; }
      setRunResult(r);
      const g = await api.evalGate();
      if (g.kind === "error") { setError(g.message); return; }
      setGate(g);
      await mutateMetrics();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const effectiveGates = editingGates ? draftGates : (gates as Record<string, number>);
  const gateRows = deriveGateRows(effectiveGates, metrics);
  const measured = gateRows.filter((r) => r.pass !== null);
  const failed = measured.filter((r) => r.pass === false);
  const verdict: "pass" | "fail" | "unknown" =
    gate ? (gate.passed ? "pass" : "fail")
    : measured.length === 0 ? "unknown"
    : failed.length === 0 ? "pass" : "fail";

  // Metrics on disk imply a completed run, so keep the sequence coherent: if
  // metrics exist, Run is "done" too (never "Run pending" beside "Metrics done").
  const evaluated = metricsData?.present ?? false;
  const steps: WizardStepDef[] = [
    { id: "author", label: "Eval sets", status: evaluated ? "done" : "current" },
    { id: "run", label: "Run",
      status: running ? "current" : (runResult || evaluated) ? "done" : "pending" },
    { id: "gate", label: "Gate",
      status: verdict === "pass" ? "done" : verdict === "fail" ? "current" : "pending" },
    { id: "metrics", label: "Metrics", status: evaluated ? "done" : "pending" },
  ];

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-extrabold text-ink">Evaluation studio</h1>
          <p className="text-sm text-ink-500 mt-1">
            Author eval sets, run them against your latest adapter, and read the
            promotion gate. These sets judge the model: they are not training data.
          </p>
        </div>
      </div>

      {!dangerous ? <LockedNote action="Running evals" /> : null}
      {error ? <Banner tone="fail">{error}</Banner> : null}

      <StepWizard steps={steps}>
      {/* ---- Step 1: author eval sets ---- */}
      <WizardSection id="author" n={1} title="Author eval sets"
        status={metricsData?.present ? "done" : "current"}
        hint="The task / safety / regression cases the gate scores against your adapter.">
        <EvalSets />
      </WizardSection>

      {/* ---- Step 2: run ---- */}
      <WizardSection id="run" n={2} title="Run the evals"
        status={running ? "current" : runResult ? "done" : "pending"}
        hint="Real generation against your adapter, then the gate is applied."
        action={
          <Button variant="primary" size="sm"
            onClick={() => void runAll()} disabled={running || !dangerous}
            title={!dangerous ? "Enable state-changing tools to run evals" : undefined}>
            {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? "Running…" : "Run evals + gate"}
          </Button>
        }>
        <Card>
          <CardBody className="text-xs text-ink-500">
            Runs the eval modules with real generation against{" "}
            <code>{config?.settings.adapter_path ?? "your adapter"}</code>, then applies the gate.
          </CardBody>
        </Card>
        {runResult ? (
          <Card>
            <CardHeader className="text-sm font-bold flex items-center gap-2">
              <FlaskConical size={14} className="text-amber-600" /> Last run
              <Badge tone={runResult.all_ok ? "ok" : "fail"}>
                {runResult.all_ok ? "all modules ok" : "a module failed"}
              </Badge>
            </CardHeader>
            <CardBody className="space-y-2">
              {runResult.modules.map((mod) => (
                <details key={mod.module} className="rounded-lg border border-ink-200 bg-card">
                  <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs font-semibold">
                    {mod.ok ? <CheckCircle2 size={13} className="text-emerald-500" />
                            : <XCircle size={13} className="text-red-500" />}
                    {mod.module}
                    <span className="ml-auto text-[10px] text-ink-400">exit {mod.exit_code}</span>
                  </summary>
                  <pre className="overflow-x-auto border-t border-ink-100 bg-[#0f1c2e] p-2.5
                                  font-mono text-[10px] leading-relaxed text-slate-100">
                    {mod.stdout_tail || "(no output)"}
                  </pre>
                </details>
              ))}
            </CardBody>
          </Card>
        ) : null}
      </WizardSection>

      {/* ---- Step 3: gate verdict ---- */}
      <WizardSection id="gate" n={3} title="Promotion gate"
        status={verdict === "pass" ? "done" : verdict === "fail" ? "current" : "pending"}
        hint="The thresholds that must pass before this adapter can be promoted."
        action={
          <div className="flex items-center gap-2">
            <GateBadge verdict={verdict} />
            {editingGates ? null : Object.keys(gates).length ? (
              <Button size="sm" variant="secondary" onClick={startEditGates}>
                <Pencil size={12} /> Edit thresholds
              </Button>
            ) : null}
          </div>
        }>
      <Card>
        <CardHeader className="flex flex-wrap items-center gap-2">
          <ShieldCheck size={15} className="text-amber-600" />
          <span className="text-sm font-bold">Gate criteria</span>
          <div className="ml-auto flex items-center gap-2">
            {editingGates ? (
              <>
                <Button size="sm" variant="ghost"
                  onClick={() => { setEditingGates(false); setGateErr(null); }}>
                  Cancel
                </Button>
                <Button size="sm" variant="primary" onClick={() => void saveGates()}
                  disabled={savingGates}>
                  {savingGates ? <Loader2 size={12} className="animate-spin" /> : null}
                  Save thresholds
                </Button>
              </>
            ) : null}
          </div>
        </CardHeader>
        <CardBody className="space-y-3">
          {gateRows.length === 0 ? (
            <div className="text-sm text-ink-500">No gate thresholds configured.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-ink-200 text-left text-[10px] uppercase tracking-wider text-ink-400">
                    <th className="py-1.5 pr-3 font-bold">Criterion</th>
                    <th className="py-1.5 pr-3 font-bold">Measured</th>
                    <th className="py-1.5 pr-3 font-bold">Requirement</th>
                    <th className="py-1.5 font-bold">Verdict</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {gateRows.map((r) => (
                    <tr key={r.key}>
                      <td className="py-1.5 pr-3 font-semibold text-ink">{prettyMetric(r.metricKey)}</td>
                      <td className="py-1.5 pr-3 tabular-nums text-ink-700">
                        {r.value != null ? fmtNum(r.value) : <span className="text-ink-400">not measured</span>}
                      </td>
                      <td className="py-1.5 pr-3 tabular-nums text-ink-500">
                        {editingGates ? (
                          <span className="inline-flex items-center gap-1">
                            {r.op}
                            <input
                              type="number" step="any" min={0}
                              value={draftGates[r.key] ?? r.threshold}
                              onChange={(e) => {
                                const n = parseFloat(e.target.value);
                                setDraftGates((prev) => ({
                                  ...prev,
                                  [r.key]: Number.isNaN(n) ? 0 : n,
                                }));
                              }}
                              className="w-24 rounded border border-ink-200 px-1.5 py-0.5
                                         text-right focus:border-accent focus:outline-none"
                            />
                          </span>
                        ) : (
                          <>{r.op} {fmtNum(r.threshold)}</>
                        )}
                      </td>
                      <td className="py-1.5">
                        {r.pass == null ? (
                          <span className="text-ink-400">n/a</span>
                        ) : r.pass ? (
                          <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                            <CheckCircle2 size={13} /> pass
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 font-semibold text-red-700">
                            <XCircle size={13} /> fail
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {gateErr ? (
            <p className="flex items-center gap-1 text-[11px] text-red-700">
              <AlertTriangle size={12} /> {gateErr}
            </p>
          ) : null}
          {editingGates ? (
            <p className="text-[11px] text-ink-500">
              Editing writes to <code>configs/eval.yaml</code> (a .bak is kept).
              The verdict above updates live as you change values.
            </p>
          ) : measured.length === 0 ? (
            <p className="text-[11px] text-ink-500">
              Run the evals to measure these against your adapter.
            </p>
          ) : null}
          {config?.settings.adapter_path ? (
            <p className="text-[10px] text-ink-400">
              Adapter under test: <code>{config.settings.adapter_path}</code>
              {config.settings.model_id ? <> · base <code>{config.settings.model_id}</code></> : null}
            </p>
          ) : null}
        </CardBody>
      </Card>
      </WizardSection>

      {/* ---- Step 4: metrics ---- */}
      <WizardSection id="metrics" n={4} title="Latest metrics"
        status={metricsData?.present ? "done" : "pending"}
        hint="The measured numbers behind the gate verdict.">
      {metricsData?.present ? (
        <Card>
          <CardBody className="space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label="task score" helpKey="task_score"
                    value={metrics.task_score != null ? Number(metrics.task_score).toFixed(3) : "-"} />
              <Stat label="safety crit" value={String(metrics.safety_failures_critical ?? 0)}
                    tone={(metrics.safety_failures_critical ?? 0) > 0 ? "fail" : "ok"} />
              <Stat label="safety high" value={String(metrics.safety_failures_high ?? 0)}
                    tone={(metrics.safety_failures_high ?? 0) > 0 ? "warn" : "ok"} />
              <Stat label="regression failures" value={String(metrics.regression_failures ?? 0)}
                    tone={(metrics.regression_failures ?? 0) > 0 ? "fail" : "ok"} />
              <Stat label="p50 latency" helpKey="p50_latency_ms"
                    value={metrics.p50_latency_ms != null ? `${Number(metrics.p50_latency_ms).toFixed(0)} ms` : "-"} />
              <Stat label="p95 latency" helpKey="p95_latency_ms"
                    value={metrics.p95_latency_ms != null ? `${Number(metrics.p95_latency_ms).toFixed(0)} ms` : "-"} />
              <Stat label="p99 latency"
                    value={metrics.p99_latency_ms != null ? `${Number(metrics.p99_latency_ms).toFixed(0)} ms` : "-"} />
              <Stat label="cost / 1k req"
                    value={metrics.cost_per_1k_requests_usd != null
                      ? `$${Number(metrics.cost_per_1k_requests_usd).toFixed(4)}` : "-"} />
            </div>
            <details className="rounded-lg border border-ink-200">
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-ink-500">Raw metrics JSON</summary>
              <pre className="overflow-x-auto border-t border-ink-100 bg-ink-50 p-3 text-[11px]">
{JSON.stringify(metricsData.metrics, null, 2)}
              </pre>
            </details>
          </CardBody>
        </Card>
      ) : (
        <Card><CardBody className="text-sm text-ink-500">
          No metrics yet. Author your eval sets above, then run the evals.
        </CardBody></Card>
      )}
      </WizardSection>
      </StepWizard>
    </div>
  );
}

interface GateRow {
  key: string; metricKey: string; threshold: number;
  value: number | undefined; op: string; pass: boolean | null;
}

function deriveGateRows(gates: Record<string, number>, metrics: Metrics): GateRow[] {
  return Object.entries(gates).map(([key, threshold]) => {
    const isMin = key.startsWith("min_");
    const isMax = key.startsWith("max_");
    const metricKey = key.replace(/^(min|max)_/, "");
    const value = metrics[metricKey];
    let pass: boolean | null = null;
    if (typeof value === "number" && (isMin || isMax)) {
      pass = isMin ? value >= threshold : value <= threshold;
    }
    return { key, metricKey, threshold, value, op: isMin ? ">=" : isMax ? "<=" : "=", pass };
  });
}

function prettyMetric(k: string): string {
  return k.replace(/_/g, " ").replace(/\bms\b/, "(ms)")
    .replace(/\busd\b/, "(USD)").replace(/\bp(\d+)\b/, "p$1");
}

function fmtNum(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n < 1 ? n.toFixed(3) : n.toFixed(2);
}

function GateBadge({ verdict }: { verdict: "pass" | "fail" | "unknown" }) {
  if (verdict === "pass") return <Badge tone="ok"><CheckCircle2 size={11} /> PASS</Badge>;
  if (verdict === "fail") return <Badge tone="fail"><XCircle size={11} /> FAIL</Badge>;
  return <Badge tone="muted">not run</Badge>;
}

function Banner({ tone, children }: { tone: "warn" | "fail"; children: React.ReactNode }) {
  return (
    <div className={cn(
      "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm",
      tone === "warn" ? "bg-amber-50 border-amber-200 text-amber-900"
                      : "bg-red-50 border-red-200 text-red-900",
    )}>
      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
}
