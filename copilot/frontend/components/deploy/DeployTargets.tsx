"use client";
/**
 * Deployment targets you can configure and actually run. Pick a target, set
 * its options, and press Deploy: Puffin runs the setup + deploy commands as a
 * tracked subprocess and streams the log. Cloud targets (Terraform) provision
 * real, billable infrastructure, so they take an extra confirm.
 */
import * as React from "react";
import useSWR from "swr";
import { AlertTriangle, Boxes, CheckCircle2, Cloud, Container, ExternalLink, Loader2, Rocket, ScrollText, Square, XCircle } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { DeployLogPayload, K8sManifest } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

interface TargetMeta {
  id: string; label: string; icon: typeof Cloud; blurb: string;
  needs?: string; docs?: string; cloud?: boolean;
}

const TARGETS: TargetMeta[] = [
  { id: "kubernetes", label: "Kubernetes", icon: Boxes,
    blurb: "Apply a Deployment + Service + autoscaler to your current kubectl cluster.",
    docs: "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/" },
  { id: "docker", label: "Docker", icon: Container,
    blurb: "Build the serving image and run it as a local container.",
    needs: "Docker running locally." },
  { id: "aws", label: "AWS", icon: Cloud, cloud: true,
    blurb: "Provision serving infrastructure on AWS with Terraform.",
    needs: "AWS credentials configured.",
    docs: "https://registry.terraform.io/providers/hashicorp/aws/latest/docs" },
  { id: "gcp", label: "Google Cloud", icon: Cloud, cloud: true,
    blurb: "Provision on GCP with Terraform.",
    needs: "gcloud auth configured.",
    docs: "https://registry.terraform.io/providers/hashicorp/google/latest/docs" },
  { id: "azure", label: "Azure", icon: Cloud, cloud: true,
    blurb: "Provision on Azure with Terraform.",
    needs: "az login configured.",
    docs: "https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs" },
];

type Settings = Record<string, string | number | boolean>;
const DEFAULTS: Record<string, Settings> = {
  kubernetes: { replicas: 2, namespace: "puffin", serving_image: "puffin-serve:latest", environment: "staging", gpu: true },
  docker: { serving_image: "puffin-serve:latest", port: 8089, backend: "transformers" },
  aws: {}, gcp: {}, azure: {},
};

function previewCmds(id: string, s: Settings): string[] {
  if (id === "kubernetes") return ["kubectl apply -f artifacts/copilot/deploy-manifest.yaml"];
  if (id === "docker") {
    const df = s.backend === "vllm" ? "Dockerfile.serve.vllm" : "Dockerfile.serve";
    return [
      `docker build -f infra/docker/${df} -t ${s.serving_image} .`,
      "docker rm -f puffin-serve",
      `docker run -d --name puffin-serve -p ${s.port}:8089 -e PUFFIN_SERVE_BACKEND=${s.backend} ${s.serving_image}`,
    ];
  }
  return ["terraform init -input=false", "terraform apply -auto-approve -input=false"];
}

export function DeployTargets() {
  const { data: caps } = useSWR("capabilities", () => api.capabilities());
  const { data: readiness } = useSWR("deploy:targets", () => api.deployTargets());
  const { data: status, mutate: mutateStatus } = useSWR("deploy:status",
    () => api.deployStatus(), { refreshInterval: 4_000 });

  const dangerous = caps?.dangerous_enabled ?? true;
  const running = status?.running ?? false;
  const readyById = React.useMemo(
    () => new Map((readiness?.targets ?? []).map((t) => [t.id, t])),
    [readiness]);

  const [id, setId] = React.useState("kubernetes");
  const target = TARGETS.find((t) => t.id === id) ?? TARGETS[0];
  const r = readyById.get(id);
  const cliOk = r?.cli_installed ?? true;

  const [settings, setSettings] = React.useState<Settings>(DEFAULTS.kubernetes);
  React.useEffect(() => { setSettings(DEFAULTS[id] ?? {}); }, [id]);

  const [busy, setBusy] = React.useState(false);
  const [confirm, setConfirm] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!confirm) return;
    const t = setTimeout(() => setConfirm(false), 5000);
    return () => clearTimeout(t);
  }, [confirm]);

  const set = (k: string, v: string | number | boolean) =>
    setSettings((prev) => ({ ...prev, [k]: v }));

  const deploy = async () => {
    setBusy(true); setErr(null); setConfirm(false);
    try {
      const res = await api.deployRun(id, settings);
      if (res.kind === "error") { setErr(res.message); return; }
      await mutateStatus();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const cancel = async () => {
    await api.deployCancel().catch(() => undefined);
    await mutateStatus();
  };

  const blockedReason = !dangerous ? "locked"
    : !cliOk ? "no-cli"
    : running ? "busy" : null;

  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        <Rocket size={15} className="text-amber-600" /> Deployment targets
        <span className="font-normal text-[11px] text-ink-500">
          configure, then deploy
        </span>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {TARGETS.map((t) => {
            const active = t.id === id;
            const tr = readyById.get(t.id);
            const Icon = t.icon;
            return (
              <button key={t.id} type="button" onClick={() => setId(t.id)}
                className={cn(
                  "flex items-center gap-2 rounded-xl border p-2.5 text-left transition-colors",
                  active ? "border-accent bg-amber-50/60 shadow-glow"
                         : "border-ink-200 bg-card hover:border-ink-300",
                )}>
                <Icon size={15} className={active ? "text-accent-600" : "text-ink-400"} />
                <span className="flex-1 text-xs font-bold text-ink">{t.label}</span>
                {tr ? (
                  <span className={cn("h-1.5 w-1.5 rounded-full",
                    tr.cli_installed ? "bg-emerald-500" : "bg-ink-300")}
                    title={tr.cli_installed ? `${tr.cli} ready` : `${tr.cli} not found`} />
                ) : null}
              </button>
            );
          })}
        </div>

        <div>
          <p className="text-sm text-ink-600">{target.blurb}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 text-[11px] text-ink-500">
            {r ? (
              <span className={cn("inline-flex items-center gap-1",
                cliOk ? "text-emerald-700" : "text-amber-700")}>
                {cliOk ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
                <code>{r.cli}</code> {cliOk ? "installed" : "not found on PATH"}
              </span>
            ) : null}
            {target.needs ? <span>Needs: {target.needs}</span> : null}
            {target.docs ? (
              <a href={target.docs} target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-1 font-semibold text-accent-600 hover:underline">
                docs <ExternalLink size={10} />
              </a>
            ) : null}
          </div>
        </div>

        {/* Per-target settings */}
        {id === "kubernetes" ? (
          <KubernetesSettings settings={settings} set={set} />
        ) : id === "docker" ? (
          <DockerSettings settings={settings} set={set} />
        ) : (
          <p className="rounded-lg bg-ink-50 p-2.5 text-[11px] text-ink-500">
            Variables (region, machine type, replicas) live in{" "}
            <code>infra/terraform/{id}/variables.tf</code>. Edit them there, then deploy.
          </p>
        )}

        {/* What Deploy will run */}
        <div>
          <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-ink-500">
            Runs
          </div>
          <pre className="overflow-x-auto rounded-lg border border-ink-800/50 bg-[#0f172a]
                          p-2.5 font-mono text-[11px] leading-relaxed text-slate-100">
            {previewCmds(id, settings).map((c, i) => <div key={i}>$ {c}</div>)}
          </pre>
        </div>

        {/* Deploy / cancel */}
        <div className="flex flex-wrap items-center gap-2">
          {running ? (
            <>
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink">
                <Loader2 size={13} className="animate-spin text-amber-600" />
                Deploying to {status?.label} (PID {status?.pid})
              </span>
              <Button size="sm" variant="danger" onClick={() => void cancel()}>
                <Square size={12} /> Cancel
              </Button>
            </>
          ) : blockedReason === "no-cli" ? (
            <span className="inline-flex items-center gap-1 text-xs text-amber-700">
              <AlertTriangle size={13} /> Install <code>{r?.cli}</code> to deploy here.
            </span>
          ) : (
            <Button
              size="sm"
              variant={confirm ? "danger" : "primary"}
              disabled={busy || !dangerous}
              onClick={() => { if (confirm) void deploy(); else setConfirm(true); }}
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Rocket size={13} />}
              {confirm
                ? (target.cloud ? "Confirm: provisions real cloud infra" : "Confirm deploy")
                : `Deploy to ${target.label}`}
            </Button>
          )}
          {target.id === "kubernetes" && !running ? <RenderManifestButton settings={settings} /> : null}
        </div>

        {target.cloud && !running ? (
          <p className="flex items-start gap-1 text-[11px] text-amber-700">
            <AlertTriangle size={11} className="mt-0.5 shrink-0" />
            Terraform apply creates real cloud resources and can incur cost. It runs
            with your local credentials.
          </p>
        ) : null}
        {!dangerous ? (
          <p className="flex items-start gap-1 text-[11px] text-amber-700">
            <AlertTriangle size={11} className="mt-0.5 shrink-0" />
            Locked: restart the backend with <code>PUFFIN_COPILOT_ENABLE_DANGEROUS=1</code> to deploy.
          </p>
        ) : null}
        {err ? (
          <p className="flex items-start gap-1 text-[11px] text-red-700">
            <XCircle size={12} className="mt-0.5 shrink-0" /> {err}
          </p>
        ) : null}

        <DeployLog live={running} />
      </CardBody>
    </Card>
  );
}

function KubernetesSettings({ settings, set }: {
  settings: Settings; set: (k: string, v: string | number | boolean) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 rounded-xl border border-ink-200 bg-ink-50/40 p-3 sm:grid-cols-3">
      <Field label="Replicas">
        <input type="number" min={1} max={100} value={Number(settings.replicas ?? 2)}
          onChange={(e) => set("replicas", parseInt(e.target.value, 10) || 1)}
          className={inputCls} />
      </Field>
      <Field label="Namespace">
        <input value={String(settings.namespace ?? "")} onChange={(e) => set("namespace", e.target.value)}
          className={inputCls} />
      </Field>
      <Field label="Environment">
        <select value={String(settings.environment ?? "staging")} onChange={(e) => set("environment", e.target.value)}
          className={inputCls}>
          <option value="staging">staging</option>
          <option value="production">production</option>
        </select>
      </Field>
      <Field label="Serving image">
        <input value={String(settings.serving_image ?? "")} onChange={(e) => set("serving_image", e.target.value)}
          className={inputCls} />
      </Field>
      <label className="flex items-end gap-1.5 pb-1 text-xs font-semibold text-ink">
        <input type="checkbox" checked={Boolean(settings.gpu)} onChange={(e) => set("gpu", e.target.checked)}
          className="h-4 w-4 accent-amber-500" />
        GPU node
      </label>
    </div>
  );
}

function DockerSettings({ settings, set }: {
  settings: Settings; set: (k: string, v: string | number | boolean) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 rounded-xl border border-ink-200 bg-ink-50/40 p-3 sm:grid-cols-3">
      <Field label="Image tag">
        <input value={String(settings.serving_image ?? "")} onChange={(e) => set("serving_image", e.target.value)}
          className={inputCls} />
      </Field>
      <Field label="Host port">
        <input type="number" min={1} max={65535} value={Number(settings.port ?? 8089)}
          onChange={(e) => set("port", parseInt(e.target.value, 10) || 8089)}
          className={inputCls} />
      </Field>
      <Field label="Backend">
        <select value={String(settings.backend ?? "transformers")} onChange={(e) => set("backend", e.target.value)}
          className={inputCls}>
          <option value="transformers">transformers</option>
          <option value="vllm">vllm</option>
        </select>
      </Field>
    </div>
  );
}

const inputCls = "w-full rounded-lg border border-ink-200 bg-card px-2 py-1 text-sm focus:border-accent focus:outline-none";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-[10px] font-bold uppercase tracking-wider text-ink-500">{label}</span>
      {children}
    </label>
  );
}

function RenderManifestButton({ settings }: { settings: Settings }) {
  const [manifest, setManifest] = React.useState<K8sManifest | null>(null);
  const [busy, setBusy] = React.useState(false);
  const preview = async () => {
    setBusy(true);
    try {
      const r = await api.deployK8s({
        replicas: Number(settings.replicas ?? 2),
        namespace: String(settings.namespace ?? "puffin"),
        serving_image: String(settings.serving_image ?? "puffin-serve:latest"),
        gpu: Boolean(settings.gpu),
        environment: String(settings.environment ?? "staging"),
      });
      if (r.kind !== "error") setManifest(r);
    } finally { setBusy(false); }
  };
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => void preview()} disabled={busy}>
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Boxes size={12} />}
        Preview manifest
      </Button>
      {manifest ? (
        <pre className="mt-2 w-full max-h-80 overflow-auto rounded-lg border border-ink-200 bg-ink-50 p-2.5 font-mono text-[10px] leading-relaxed text-ink-700">
          {manifest.yaml}
        </pre>
      ) : null}
    </>
  );
}

function DeployLog({ live }: { live: boolean }) {
  const [open, setOpen] = React.useState(false);
  const { data } = useSWR<DeployLogPayload>(
    open || live ? "deploy:log" : null, () => api.deployLog(400),
    { refreshInterval: live ? 3_000 : 0 });
  const preRef = React.useRef<HTMLPreElement>(null);
  React.useEffect(() => { if (open) return; if (live) setOpen(true); }, [live, open]);
  React.useEffect(() => {
    if (live && preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight;
  }, [data, live]);

  return (
    <div className="rounded-lg border border-ink-200">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-bold uppercase tracking-wider text-ink-500 hover:text-ink">
        <ScrollText size={13} className={open ? "text-accent-600" : "text-ink-400"} />
        Deploy log
        {data?.present && typeof data.total_lines === "number" ? (
          <span className="font-normal normal-case tracking-normal text-ink-400">{data.total_lines} lines</span>
        ) : null}
        <span className="ml-auto text-[10px] font-semibold text-accent-600">{open ? "hide" : "view"}</span>
      </button>
      {open ? (
        <div className="border-t border-ink-100 p-2">
          {!data ? (
            <div className="px-2 py-3 text-[11px] text-ink-400">Reading log…</div>
          ) : !data.present ? (
            <div className="px-2 py-3 text-[11px] text-ink-400">{data.message ?? "No deploy log yet."}</div>
          ) : (
            <pre ref={preRef}
              className="max-h-96 overflow-auto rounded-md bg-[#0f172a] p-2.5 font-mono text-[10px] leading-relaxed text-slate-100">
              {data.lines.map((ln, i) => (
                <div key={i} className={cn(
                  /\b(error|failed|denied|not found|fatal)\b/i.test(ln) ? "text-red-300"
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
