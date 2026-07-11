"use client";
/**
 * Deploy studio: push a trained adapter to the local registry, promote it
 * between aliases (candidate -> staging -> production), and see whether the
 * promotion gate actually passed. Everything is playable: push, re-point
 * aliases, then try the result in the Playground.
 */
import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, Package, Play, ShieldCheck, Upload, XCircle } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { DeployPromoteResult, DeployPushResult } from "@/lib/api";
import type { RegistryPayload } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LockedNote } from "@/components/ui/LockedNote";
import { ServerHealthCard } from "@/components/artifacts/ServerHealthCard";
import { ServeControl } from "@/components/serve/ServeControl";
import { DeployTargets } from "@/components/deploy/DeployTargets";
import { StepWizard, WizardSection, type WizardStepDef } from "@/components/layout/StepWizard";
import { cn } from "@/lib/cn";

const ALIASES = ["candidate", "staging", "production", "archived"] as const;
type Alias = (typeof ALIASES)[number];

export default function DeployPage() {
  const { data: registry, mutate: mutateRegistry } = useSWR("registry", () => api.registry());
  const { data: deployCfg } = useSWR("deploy-config", () => api.deployConfig());
  const { data: gate } = useSWR("eval-gate-report", () => api.evalGateReport());
  const { data: evalCfg } = useSWR("eval-config", () => api.evalConfig());
  const { data: evalMetricsData } = useSWR("eval", () => api.evalMetrics());
  const { data: caps } = useSWR("capabilities", () => api.capabilities());
  const { data: health } = useSWR("serving:health",
    () => api.servingHealth(), { refreshInterval: 10_000 });

  const dangerous = caps?.dangerous_enabled ?? true;
  const gateKnown = gate?.present ?? false;
  const gatePassed = gateKnown && gate?.passed === true;

  const name = deployCfg?.name ?? "my-model";
  const models = registry?.models ?? [];
  const gateThresholds = evalCfg?.gates ?? {};
  const gateMetrics = (evalMetricsData?.metrics ?? {}) as Record<string, number | undefined>;

  const steps: WizardStepDef[] = [
    { id: "readiness", label: "Readiness",
      status: gatePassed ? "done" : gateKnown ? "current" : "pending" },
    { id: "push", label: "Push", status: models.length ? "done" : "current" },
    { id: "registry", label: "Registry", status: models.length ? "done" : "pending",
      badge: models.length || undefined },
    { id: "serve", label: "Serve", status: "pending" },
  ];

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-extrabold text-ink">Deploy</h1>
          <p className="text-sm text-ink-500 mt-1">
            Push the adapter to the registry, promote it between aliases, and
            try it in the Playground.
          </p>
        </div>
      </div>

      <StepWizard steps={steps}>
      {/* ---- Step 1: promotion readiness ---- */}
      <WizardSection id="readiness" n={1} title="Promotion readiness"
        status={gatePassed ? "done" : gateKnown ? "current" : "pending"}
        hint="Whether the promotion gate passed. You can still force a push, but a failing gate means deploying is a deliberate override.">
      <GateReadiness
        gateKnown={gateKnown}
        gatePassed={gatePassed}
        failures={gate?.failures ?? []}
        thresholds={gateThresholds}
        metrics={gateMetrics}
      />
      </WizardSection>

      {/* ---- Step 2: push ---- */}
      <WizardSection id="push" n={2} title="Push to registry"
        status={models.length ? "done" : "current"}
        hint="Register artifacts/adapter as a new immutable version and optionally point an alias at it.">
        <PushCard
          defaultName={name}
          dangerous={dangerous}
          gatePassed={gatePassed}
          onDone={() => void mutateRegistry()}
        />
      </WizardSection>

      {/* ---- Step 3: registry + promote ---- */}
      <WizardSection id="registry" n={3} title="Registry and aliases"
        status={models.length ? "done" : "pending"}
        hint="Every pushed version, and where candidate / staging / production point. Re-point an alias to promote or roll back.">
      <Card>
        <CardHeader className="flex items-center gap-2 text-sm font-bold">
          <Package size={15} className="text-amber-600" /> Registry
          <span className="font-normal text-[11px] text-ink-500">
            artifacts/_registry: versions and where each alias points
          </span>
        </CardHeader>
        <CardBody className="space-y-4">
          {models.length === 0 ? (
            <div className="text-sm text-ink-500">
              No models yet. Push the adapter above to create the first version.
            </div>
          ) : models.map((m) => (
            <ModelBlock key={m.name} model={m} dangerous={dangerous}
              onPromoted={() => void mutateRegistry()} />
          ))}
        </CardBody>
      </Card>
      </WizardSection>

      {/* ---- Step 4: serve + try ---- */}
      <WizardSection id="serve" n={4} title="Serve and try it"
        status="pending"
        hint="Start a local server for the promoted adapter, check its health, and open other deployment targets.">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ServeControl />
        {health ? <ServerHealthCard data={health} /> : null}
      </div>
      <DeployTargets />
      </WizardSection>
      </StepWizard>
    </div>
  );
}

/* ---- Promotion readiness: per-criterion gate checklist ---- */
interface GateRow {
  key: string; metricKey: string; threshold: number;
  value: number | undefined; op: string; pass: boolean | null;
}

function deriveGateRows(
  gates: Record<string, number>, metrics: Record<string, number | undefined>,
): GateRow[] {
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
  return k.replace(/_/g, " ").replace(/\bms\b/, "(ms)").replace(/\busd\b/, "(USD)");
}
function fmtGateNum(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n < 1 ? n.toFixed(3) : n.toFixed(2);
}

function GateReadiness({
  gateKnown, gatePassed, failures, thresholds, metrics,
}: {
  gateKnown: boolean;
  gatePassed: boolean;
  failures: string[];
  thresholds: Record<string, number>;
  metrics: Record<string, number | undefined>;
}) {
  const rows = deriveGateRows(thresholds, metrics);
  const measured = rows.filter((r) => r.pass !== null);
  const failingRows = measured.filter((r) => r.pass === false);
  const notMeasured = rows.length - measured.length;
  // "not measured" is NOT "failing": if nothing has been measured for this
  // adapter, the gate simply hasn't been evaluated yet — don't cry FAIL.
  const realFailCount = failingRows.length;
  const unevaluated = gateKnown && !gatePassed && realFailCount === 0 && notMeasured > 0;
  const plural = (n: number) => `criteri${n === 1 ? "on" : "a"}`;

  return (
    <div className="space-y-3">
      {/* Summary banner: caution (not alarm) when merely unevaluated. */}
      <div className={cn(
        "flex flex-wrap items-center gap-2 rounded-xl border px-4 py-3",
        !gateKnown || unevaluated ? "border-warn/40 bg-warn/10"
          : gatePassed ? "border-emerald-300 bg-emerald-50/60"
          : "border-red-300 bg-red-50/60",
      )}>
        <ShieldCheck size={18} className={cn("shrink-0",
          !gateKnown || unevaluated ? "text-warn" : gatePassed ? "text-emerald-600" : "text-red-600")} />
        <div className="min-w-0 flex-1 text-sm">
          {!gateKnown ? (
            <span className="font-bold text-ink">Gate not run yet: evaluate this adapter first.</span>
          ) : gatePassed ? (
            <span className="font-bold text-emerald-800">Gate passed: safe to promote.</span>
          ) : unevaluated ? (
            <span className="text-ink"><b>Not evaluated yet</b> — {notMeasured} {plural(notMeasured)} unmeasured. Run evals to see readiness.</span>
          ) : (
            <span className="font-bold text-red-800">
              {realFailCount} {plural(realFailCount)} failing: pushing is a deliberate override.
            </span>
          )}
        </div>
        {(!gateKnown || unevaluated) ? (
          <Link href="/evaluate"
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs
                       font-semibold text-ink-50 shadow-glow transition-colors hover:bg-accent-400">
            <Play size={12} /> Run evals
          </Link>
        ) : (
          <Link href="/evaluate"
            className="inline-flex items-center gap-1 text-xs font-semibold text-accent-600 hover:text-accent">
            {gatePassed ? "Review in Evaluate" : "Fix in Evaluate"} <ArrowRight size={12} />
          </Link>
        )}
      </div>

      {/* Per-criterion checklist */}
      {rows.length ? (
        <>
        <div className="overflow-x-auto rounded-xl border border-ink-200">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-ink-200 bg-card-muted text-left text-[10px] uppercase tracking-wider text-ink-400">
                <th className="px-4 py-2 font-bold">Criterion</th>
                <th className="px-4 py-2 text-right font-bold">Measured</th>
                <th className="px-4 py-2 text-right font-bold">Requirement</th>
                <th className="px-4 py-2 text-right font-bold">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {rows.map((r) => (
                <tr key={r.key} className={r.pass === false ? "bg-red-50/40" : undefined}>
                  <td className="px-4 py-2 font-semibold text-ink">{prettyMetric(r.metricKey)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-ink-700">
                    {r.value != null ? fmtGateNum(r.value) : <span className="text-ink-400">not measured</span>}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-ink-500">
                    {r.op} {fmtGateNum(r.threshold)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {r.pass == null ? (
                      <span className="text-ink-400">n/a</span>
                    ) : r.pass ? (
                      <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                        <CheckCircle2 size={12} /> pass
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 font-semibold text-red-700">
                        <XCircle size={12} /> fail
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {notMeasured > 0 && !unevaluated ? (
          <p className="text-[11px] text-ink-500">
            {notMeasured} {plural(notMeasured)} not measured yet; the failing verdict above
            is based on what has run so far.
          </p>
        ) : null}
        </>
      ) : failures.length ? (
        <ul className="space-y-1.5">
          {failures.map((f) => (
            <li key={f} className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50/50 px-3 py-2 text-xs">
              <XCircle size={13} className="shrink-0 text-red-600" />
              <span className="font-semibold text-ink">{prettyMetric(f.replace(/^(min|max)_/, ""))}</span>
              <span className="text-ink-500">below its promotion threshold</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-500">
          Run the evals on Evaluate to see each promotion criterion measured against its threshold here.
        </p>
      )}
    </div>
  );
}

function PushCard({
  defaultName, dangerous, gatePassed, onDone,
}: {
  defaultName: string;
  dangerous: boolean;
  gatePassed: boolean;
  onDone: () => void;
}) {
  const [name, setName] = React.useState(defaultName);
  const [alias, setAlias] = React.useState<Alias>("candidate");
  const [busy, setBusy] = React.useState(false);
  const [confirmForce, setConfirmForce] = React.useState(false);
  const [result, setResult] = React.useState<DeployPushResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => { setName(defaultName); }, [defaultName]);
  React.useEffect(() => {
    if (!confirmForce) return;
    const t = setTimeout(() => setConfirmForce(false), 4000);
    return () => clearTimeout(t);
  }, [confirmForce]);

  const doPush = async () => {
    setBusy(true); setErr(null); setResult(null); setConfirmForce(false);
    try {
      const r = await api.deployPush({ name: name.trim() || "my-model", alias });
      if (r.kind === "error") { setErr(r.message); return; }
      setResult(r);
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const needsForce = !gatePassed;

  return (
    <Card>
      <CardHeader className="text-sm font-bold flex items-center gap-2">
        <Upload size={14} className="text-amber-600" /> Push to registry
      </CardHeader>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1">
            <span className="block text-[11px] font-semibold text-ink-500">Model name</span>
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="w-56 rounded-lg border border-ink-200 px-2.5 py-1.5 text-sm
                         focus:border-accent focus:outline-none" />
          </label>
          <label className="space-y-1">
            <span className="block text-[11px] font-semibold text-ink-500">Assign alias</span>
            <select value={alias} onChange={(e) => setAlias(e.target.value as Alias)}
              className="rounded-lg border border-ink-200 bg-card px-2.5 py-1.5 text-sm
                         focus:border-accent focus:outline-none">
              {ALIASES.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <div className="ml-auto">
            {needsForce ? (
              <Button variant={confirmForce ? "danger" : "secondary"}
                disabled={busy || !dangerous}
                onClick={() => { if (confirmForce) void doPush(); else setConfirmForce(true); }}>
                {busy ? <Loader2 size={14} className="animate-spin" />
                      : <AlertTriangle size={14} />}
                {confirmForce ? "Confirm force push" : "Force push (gate not passed)"}
              </Button>
            ) : (
              <Button variant="primary" disabled={busy || !dangerous} onClick={() => void doPush()}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                Push to registry
              </Button>
            )}
          </div>
        </div>

        <p className="text-[11px] text-ink-500">
          Pushes <code>artifacts/adapter</code> as a new version
          {alias !== "candidate" ? <> and points <b>{alias}</b> at it</> : null}.
          {needsForce ? " The gate hasn't passed, so this is a manual override." : null}
        </p>

        {!dangerous ? <LockedNote action="Pushing to the registry" /> : null}
        {err ? (
          <p className="flex items-start gap-1 text-[11px] text-red-700">
            <XCircle size={12} className="mt-0.5 shrink-0" /> {err}
          </p>
        ) : null}
        {result ? (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
            <div>
              Pushed <code>{result.uri}</code>
              {result.alias_set ? <> and set alias <b>{result.alias}</b></> : null}.
              {result.warning ? <div className="mt-0.5 text-amber-700">{result.warning}</div> : null}
            </div>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ModelBlock({
  model, dangerous, onPromoted,
}: {
  model: RegistryPayload["models"][number];
  dangerous: boolean;
  onPromoted: () => void;
}) {
  // Reverse the alias map: version -> [aliases pointing at it].
  const aliasesByVersion = React.useMemo(() => {
    const m = new Map<string, string[]>();
    for (const [al, ver] of Object.entries(model.aliases)) {
      const arr = m.get(ver) ?? [];
      arr.push(al);
      m.set(ver, arr);
    }
    return m;
  }, [model.aliases]);

  return (
    <div className="rounded-xl border border-ink-200">
      <div className="border-b border-ink-100 px-3 py-2 text-sm font-bold text-ink">
        {model.name}
        <span className="ml-2 text-[11px] font-normal text-ink-400">
          {model.versions.length} version{model.versions.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="divide-y divide-ink-100">
        {[...model.versions].reverse().map((v) => (
          <VersionRow
            key={v.version}
            name={model.name}
            version={v.version}
            registeredAt={v.registered_at}
            aliases={aliasesByVersion.get(v.version) ?? []}
            dangerous={dangerous}
            onPromoted={onPromoted}
          />
        ))}
      </div>
    </div>
  );
}

function VersionRow({
  name, version, registeredAt, aliases, dangerous, onPromoted,
}: {
  name: string;
  version: string;
  registeredAt: string;
  aliases: string[];
  dangerous: boolean;
  onPromoted: () => void;
}) {
  const [target, setTarget] = React.useState<Alias>("staging");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<DeployPromoteResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  const promote = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api.deployPromote({ name, version, alias: target });
      if (r.kind === "error") { setErr(r.message); return; }
      setMsg(r);
      onPromoted();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2">
      <code className="text-xs font-bold text-ink">v{version}</code>
      {aliases.map((a) => (
        <Badge key={a} tone={a === "production" ? "ok" : a === "staging" ? "info" : "muted"}>{a}</Badge>
      ))}
      {registeredAt ? (
        <span className="text-[10px] text-ink-400">{new Date(registeredAt).toLocaleString()}</span>
      ) : null}
      <div className="ml-auto flex items-center gap-1.5">
        <select value={target} onChange={(e) => setTarget(e.target.value as Alias)}
          className="rounded-lg border border-ink-200 bg-card px-2 py-1 text-[11px]
                     focus:border-accent focus:outline-none">
          {ALIASES.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <Button size="sm" variant="secondary" disabled={busy || !dangerous} onClick={() => void promote()}>
          {busy ? <Loader2 size={11} className="animate-spin" /> : <ArrowRight size={11} />}
          Promote
        </Button>
      </div>
      {msg ? (
        <div className="w-full text-[11px] text-emerald-700">{msg.message}</div>
      ) : null}
      {err ? (
        <div className="w-full text-[11px] text-red-700">{err}</div>
      ) : null}
    </div>
  );
}
