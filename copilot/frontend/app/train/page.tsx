"use client";
/**
 * Train Studio: launch fine-tuning without touching YAML.
 *
 * Two modes:
 *   Recipes: curated presets grouped by category (Get started, Efficient,
 *            Big models, ...) with plain-English guidance. Pick, smoke, launch.
 *   Custom : every knob the backend exposes. The essentials show by default;
 *            "show all" reveals the full optimizer/memory/loss surface.
 *
 * Launches go through POST /api/train/launch which materializes
 * configs/train_studio.yaml from the base config + overrides and starts
 * the same subprocess a chat-launched run would use.
 */
import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, BookOpen, Check, ChevronDown, ChevronLeft, ChevronRight, Cloud, Copy, Cpu, ExternalLink, Eye, Flame, Loader2, PenLine, RotateCcw, Save, Scale, Search, Server, Sliders, Trash2, X, Zap } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type {
  CloudTarget, StudioCatalog, StudioKnob, StudioMethod, StudioRecipe,
  TrainLaunchResult,
} from "@/lib/api";
import type { LiveTrainingPayload, ProjectStatus } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { LockedNote } from "@/components/ui/LockedNote";
import { LiveTrainingCard } from "@/components/artifacts/LiveTrainingCard";
import { EnvGroupInstaller } from "@/components/train/EnvironmentPanel";
import { TrainingLogPanel } from "@/components/train/TrainingLogPanel";
import { ReadinessPanel } from "@/components/train/ReadinessPanel";
import { useLiveTraining } from "@/lib/hooks/useLiveTraining";
import { cn } from "@/lib/cn";

const RECIPE_ICONS: Record<string, typeof Zap> = {
  "zap": Zap, "pen-line": PenLine, "book-open": BookOpen,
  "cpu": Cpu, "flame": Flame, "scale": Scale,
};

type LaunchBody = {
  method: StudioMethod; smoke: boolean;
  recipe?: string | null; overrides?: Record<string, unknown>;
};

// Common, openly-available bases offered as autocomplete for the base_model
// field. Not a whitelist — you can type any HF id — just a nudge past the
// blank box toward models known to fine-tune well.
const BASE_MODEL_SUGGESTIONS = [
  "HuggingFaceTB/SmolLM2-135M-Instruct",
  "HuggingFaceTB/SmolLM2-1.7B-Instruct",
  "meta-llama/Llama-3.2-1B-Instruct",
  "meta-llama/Llama-3.2-3B-Instruct",
  "meta-llama/Llama-3.1-8B-Instruct",
  "mistralai/Mistral-7B-Instruct-v0.3",
  "Qwen/Qwen2.5-7B-Instruct",
  "google/gemma-2-9b-it",
  "microsoft/Phi-3.5-mini-instruct",
];

export default function TrainPage() {
  const live = useLiveTraining();
  const { data: catalog, error: catalogError, mutate: mutateCatalog } =
    useSWR<StudioCatalog>("train-studio", () => api.trainStudio());
  const { data: state } = useSWR<{ status: ProjectStatus }>(
    "state", () => api.state(), { refreshInterval: 10_000 });

  const [result, setResult] = React.useState<TrainLaunchResult | null>(null);
  const [launchError, setLaunchError] = React.useState<string | null>(null);
  const [launching, setLaunching] = React.useState(false);
  const [lastBody, setLastBody] = React.useState<LaunchBody | null>(null);

  const dataReady = state?.status?.steps
    ?.find((s) => s.key === "data")?.status === "done";

  const launch = React.useCallback(async (body: LaunchBody) => {
    setLaunching(true);
    setLaunchError(null);
    setResult(null);
    setLastBody(body);
    try {
      setResult(await api.trainLaunch(body));
    } catch (e) {
      setLaunchError(e instanceof Error ? e.message : String(e));
    } finally {
      setLaunching(false);
    }
  }, []);

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-ink">Train a model</h1>
          <p className="text-sm text-ink-500 mt-1">
            Pick a recipe or tune every knob: smoke-test first, then go full.
            {" "}
            <Link href="/runs" className="text-accent-600 underline underline-offset-2">
              Past runs →
            </Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {catalog ? <GpuChip gpu={catalog.gpu} /> : null}
        </div>
      </div>

      {state && !dataReady ? (
        <Banner tone="warn" icon={AlertTriangle}>
          Your data pipeline hasn&apos;t produced training splits yet: training
          will fail without <code>data/processed/train.jsonl</code>.{" "}
          <Link href="/data" className="font-semibold underline underline-offset-2">
            Prepare data first →
          </Link>
        </Banner>
      ) : null}

      {catalog && !catalog.dangerous_enabled ? (
        <LockedNote action="Launching training" />
      ) : null}

      {catalogError ? (
        <Banner tone="fail" icon={AlertTriangle}>
          Couldn&apos;t load the studio catalog: {String(catalogError)}
        </Banner>
      ) : null}

      {live?.active ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
              Live
            </div>
            {live.run?.pid ? (
              <Button
                size="sm" variant="danger"
                onClick={() => api.trainCancel(live.run!.pid!)}
              >
                Stop run
              </Button>
            ) : null}
          </div>
          <LiveTrainingCard data={live as LiveTrainingPayload} />
          {live.run?.adapter_dir ? (
            <TrainingLogPanel adapterDir={live.run.adapter_dir} live />
          ) : null}
        </div>
      ) : null}

      {!catalog ? (
        <div className="text-sm text-ink-500 py-10 text-center">
          Loading studio…
        </div>
      ) : (
        <Studio
          catalog={catalog}
          launching={launching}
          onLaunch={launch}
          onRecipesChanged={() => void mutateCatalog()}
        />
      )}

      {launchError ? (
        <Banner tone="fail" icon={AlertTriangle}>{launchError}</Banner>
      ) : null}
      {result ? (
        <LaunchResultCard
          result={result}
          lastBody={lastBody}
          launching={launching}
          onRelaunch={(smoke) => { if (lastBody) void launch({ ...lastBody, smoke }); }}
        />
      ) : null}
    </div>
  );
}

/* ────────────────────────── Compute target ────────────────────────── */

function ComputeTargetSelector({
  targets, value, onChange,
}: {
  targets: CloudTarget[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-bold uppercase tracking-wider text-ink-500">
        Where should this run?
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {targets.map((t) => {
          const active = t.id === value;
          const Icon = t.kind === "local" ? Server : Cloud;
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              className={cn(
                "text-left rounded-xl border p-3 transition-colors",
                active ? "border-accent bg-amber-50/60 shadow-glow"
                       : "border-ink-200 bg-card hover:border-ink-300",
              )}
            >
              <div className="flex items-center gap-2">
                <Icon size={15} className={active ? "text-accent-600" : "text-ink-400"} />
                <span className="text-sm font-bold text-ink">{t.label}</span>
                {active ? <Check size={14} className="ml-auto text-accent-600" /> : null}
              </div>
              <p className="mt-1 text-[11px] leading-snug text-ink-500">{t.blurb}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ──────────────────────── Step-by-step studio ──────────────────────── */

const METHOD_STEP = "__method";
const RUN_STEP = "__run";

const METHODS: Array<{ id: StudioMethod; label: string; blurb: string; data: string }> = [
  { id: "sft", label: "SFT / LoRA",
    blurb: "Supervised fine-tuning on example conversations. Teach tone, format, or domain knowledge. The usual starting point.",
    data: "chat or prompt/completion examples" },
  { id: "dpo", label: "DPO",
    blurb: "Direct Preference Optimization on chosen/rejected pairs. Sharpen behavior once you have preference data.",
    data: "preference pairs: prompt, chosen, rejected" },
  { id: "kto", label: "KTO",
    blurb: "Kahneman-Tversky Optimization. Align from cheap unpaired thumbs-up / thumbs-down feedback.",
    data: "unpaired: prompt, completion, label (bool)" },
  { id: "reward", label: "Reward model",
    blurb: "Train a scalar reward model from preference pairs. It scores answers and feeds GRPO / RLOO / PPO.",
    data: "preference pairs: chosen, rejected" },
  { id: "grpo", label: "GRPO",
    blurb: "Online RL. The model samples several completions per prompt and is pushed toward the better-rewarded ones (no value model).",
    data: "prompts + a reward (built-in or a reward model)" },
  { id: "rloo", label: "RLOO",
    blurb: "REINFORCE Leave-One-Out. Lightweight online RL: baseline each sample against the rest of its group.",
    data: "prompts + a reward (built-in or a reward model)" },
];

function Studio({
  catalog, launching, onLaunch, onRecipesChanged,
}: {
  catalog: StudioCatalog;
  launching: boolean;
  onLaunch: (body: {
    method: StudioMethod; smoke: boolean;
    recipe?: string | null; overrides?: Record<string, unknown>;
  }) => void;
  onRecipesChanged: () => void;
}) {
  const [targetId, setTargetId] = React.useState("local");
  const [method, setMethod] = React.useState<StudioMethod>("sft");
  const [edits, setEdits] = React.useState<Record<string, unknown>>({});
  const [loaded, setLoaded] = React.useState<StudioRecipe | null>(null);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [saveOpen, setSaveOpen] = React.useState(false);
  const [preview, setPreview] = React.useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = React.useState(false);
  const [stepIdx, setStepIdx] = React.useState(0);

  const target = catalog.cloud_targets.find((t) => t.id === targetId)
    ?? catalog.cloud_targets[0];
  const isLocal = !target || target.kind === "local";

  const current = catalog.current[method] ?? {};
  const forMethod = catalog.knobs.filter((k) => k.methods.includes(method));

  // The wizard: one step per non-empty knob group, bracketed by a "method &
  // recipe" first step and a "where to run" last step. Every setting is shown
  // (no essentials/show-all split) — you step through the decisions in order.
  const groupSteps = catalog.group_order
    .map((g) => ({ id: g, label: g, knobs: forMethod.filter((k) => k.group === g) }))
    .filter((g) => g.knobs.length > 0);
  const steps: Array<{ id: string; label: string }> = [
    { id: METHOD_STEP, label: "Method & recipe" },
    ...groupSteps.map((g) => ({ id: g.id, label: g.label })),
    { id: RUN_STEP, label: "Where to run" },
  ];
  const idx = Math.min(stepIdx, steps.length - 1);
  const step = steps[idx];
  const changeCount = Object.keys(edits).length;
  const stepChanges = (id: string) => {
    const g = groupSteps.find((s) => s.id === id);
    return g ? g.knobs.filter((k) => k.path in edits).length : 0;
  };

  // ── Top tab strip: two-ink indicator + direction-aware panel (globals.css) ──
  const prevStepRef = React.useRef(idx);
  const forward = idx >= prevStepRef.current;
  const stripRef = React.useRef<HTMLDivElement>(null);
  const btnRefs = React.useRef<Array<HTMLButtonElement | null>>([]);
  const indRef = React.useRef<HTMLSpanElement>(null);
  const ghostRef = React.useRef<HTMLSpanElement>(null);
  const place = React.useCallback(() => {
    const btn = btnRefs.current[idx];
    if (!btn) return;
    [indRef.current, ghostRef.current].forEach((el) => {
      if (!el) return;
      el.style.setProperty("--rx", `${btn.offsetLeft}px`);
      el.style.setProperty("--rw", `${btn.offsetWidth}px`);
    });
  }, [idx, method, steps.length]);
  React.useLayoutEffect(() => { place(); }, [place]);
  React.useEffect(() => {
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [place]);
  const goStep = (i: number) => {
    prevStepRef.current = idx;
    setStepIdx(Math.max(0, Math.min(steps.length - 1, i)));
  };
  const onStepKey = (e: React.KeyboardEvent, i: number) => {
    let n: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % steps.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + steps.length) % steps.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = steps.length - 1;
    if (n !== null) { e.preventDefault(); goStep(n); btnRefs.current[n]?.focus(); }
  };

  const setKnob = (path: string, value: unknown) => {
    setPreview(null);
    setEdits((prev) => {
      const next = { ...prev };
      if (value === current[path] || value === "" || value === undefined) {
        delete next[path];
      } else {
        next[path] = value;
      }
      return next;
    });
  };
  const switchMethod = (m: StudioMethod) => {
    prevStepRef.current = idx;
    setMethod(m); setEdits({}); setLoaded(null); setPreview(null); setStepIdx(0);
  };
  const loadRecipe = (r: StudioRecipe) => {
    setMethod(r.method);
    setEdits({ ...(r.overrides as Record<string, unknown>) });
    setLoaded(r); setPreview(null); setPickerOpen(false);
  };
  const clearAll = () => { setEdits({}); setLoaded(null); setPreview(null); };
  const doPreview = async () => {
    setPreviewOpen(true);
    try {
      setPreview((await api.trainPreview({ method, overrides: edits })).yaml);
    } catch (e) {
      setPreview(`# preview failed:\n# ${e instanceof Error ? e.message : e}`);
    }
  };

  return (
    <div className="space-y-4">
      {/* Top tab strip — the step nav, printed in two inks. */}
      <div
        ref={stripRef} role="tablist" aria-label="Train studio steps"
        className="relative flex flex-nowrap gap-1 overflow-x-auto border-b-2 border-ink-200 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        <span ref={ghostRef} className="rtabs-ghost" aria-hidden />
        <span ref={indRef} className="rtabs-ind" aria-hidden />
        {steps.map((s, i) => {
          const on = i === idx;
          const changes = stepChanges(s.id);
          const isRun = s.id === RUN_STEP;
          return (
            <button
              key={s.id} type="button" role="tab"
              aria-selected={on} aria-current={on ? "step" : undefined}
              tabIndex={on ? 0 : -1}
              ref={(el) => { btnRefs.current[i] = el; }}
              onClick={() => goStep(i)}
              onKeyDown={(e) => onStepKey(e, i)}
              className={cn(
                "relative z-[2] -mb-0.5 flex items-center gap-2 whitespace-nowrap px-3.5 py-2.5",
                "font-display text-[15px] font-semibold uppercase tracking-wide",
                "transition-[color,transform] duration-300 ease-out",
                on ? "text-ink-50" : "text-ink-500 hover:-translate-y-px hover:text-ink",
              )}
            >
              <span className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                on ? "bg-ink-50/25 text-ink-50"
                   : isRun ? "bg-emerald-100 text-emerald-700"
                   : "bg-ink-100 text-ink-500",
              )}>
                {isRun ? <Server size={11} /> : i + 1}
              </span>
              <span>{s.label}</span>
              {changes > 0 ? (
                <span className={cn(
                  "rounded-full px-1.5 text-[9px] font-bold",
                  on ? "bg-ink-50/25 text-ink-50" : "bg-amber-100 text-amber-700",
                )}>
                  {changes}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="min-w-0 space-y-4 pt-5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="font-display text-xl font-bold uppercase tracking-wide text-ink">{step.label}</h2>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">
            Step {idx + 1} of {steps.length}
          </span>
          <span className="ml-auto text-xs text-ink-500">
            {changeCount === 0
              ? "using base config as-is"
              : `${changeCount} setting${changeCount === 1 ? "" : "s"} changed`}
            {" · base "}<code>{catalog.base_config[method]}</code>
          </span>
        </div>

        {/* keyed so the entrance animation replays each step change */}
        <div key={step.id} className={cn("rtab-panel", !forward && "rev")}>
          {step.id === METHOD_STEP ? (
            <MethodStep
              method={method} loaded={loaded} changeCount={changeCount}
              onMethod={switchMethod} onLoad={() => setPickerOpen(true)}
              onSave={() => setSaveOpen(true)} onClear={clearAll} />
          ) : step.id === RUN_STEP ? (
            <div className="space-y-4">
              <ComputeTargetSelector
                targets={catalog.cloud_targets} value={targetId} onChange={setTargetId} />
              <ReadinessPanel method={method} edits={edits} local={isLocal} />
              {isLocal ? (
                <LocalLaunch
                  catalog={catalog} method={method} edits={edits}
                  forceSmoke={Boolean(loaded?.force_smoke)}
                  launching={launching} onLaunch={onLaunch} />
              ) : (
                <CloudLaunch target={target!} method={method} edits={edits} loaded={loaded} />
              )}
            </div>
          ) : (
            <GroupStep
              knobs={groupSteps.find((g) => g.id === step.id)?.knobs ?? []}
              edits={edits} current={current} onKnob={setKnob} />
          )}
        </div>

        <WizardNav
          idx={idx} total={steps.length}
          onBack={() => goStep(idx - 1)}
          onNext={() => goStep(idx + 1)}
          onPreview={doPreview} />
        {previewOpen ? (
          <pre className="text-[11px] leading-relaxed bg-ink-50 border border-ink-200
                          rounded-lg p-3 overflow-x-auto max-h-80 overflow-y-auto">
            {preview ?? "…"}
          </pre>
        ) : null}
      </div>

      {pickerOpen ? (
        <RecipePickerModal
          catalog={catalog}
          onPick={loadRecipe}
          onClose={() => setPickerOpen(false)}
          onRecipesChanged={onRecipesChanged}
        />
      ) : null}
      {saveOpen ? (
        <SaveRecipeModal
          method={method} overrides={edits}
          onClose={() => setSaveOpen(false)}
          onSaved={() => { onRecipesChanged(); }}
        />
      ) : null}
    </div>
  );
}

/* ────────────────────────── Wizard pieces ────────────────────────── */

function MethodStep({
  method, loaded, changeCount, onMethod, onLoad, onSave, onClear,
}: {
  method: StudioMethod;
  loaded: StudioRecipe | null;
  changeCount: number;
  onMethod: (m: StudioMethod) => void;
  onLoad: () => void;
  onSave: () => void;
  onClear: () => void;
}) {
  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <div className="mb-2 text-sm font-semibold text-ink">What kind of fine-tune?</div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {METHODS.map((m) => {
              const active = m.id === method;
              return (
                <button key={m.id} type="button" onClick={() => onMethod(m.id)}
                  className={cn(
                    "flex min-h-[8.5rem] flex-col rounded-xl border p-3 text-left transition-colors",
                    active ? "border-accent bg-amber-50/60 shadow-glow"
                           : "border-ink-200 bg-card hover:border-ink-300",
                  )}>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-ink">{m.label}</span>
                    {active ? <Check size={14} className="ml-auto text-accent-600" /> : null}
                  </div>
                  <p className="mt-1 text-[11px] leading-snug text-ink-500">{m.blurb}</p>
                  <p className="mt-1.5 text-[10px] font-semibold text-ink-500">
                    Data: {m.data}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3">
          <Button size="sm" variant="secondary" onClick={onLoad}>
            <BookOpen size={13} /> Load a recipe
          </Button>
          <Button size="sm" variant="ghost" onClick={onSave} disabled={changeCount === 0}
            title={changeCount === 0 ? "Change a setting first" : "Save these settings as a recipe"}>
            <Save size={13} /> Save as recipe
          </Button>
          {changeCount > 0 ? (
            <Button size="sm" variant="ghost" onClick={onClear}>
              <RotateCcw size={13} /> Reset all
            </Button>
          ) : null}
        </div>
        {loaded ? <LoadedRecipeBanner recipe={loaded} onClear={onClear} /> : null}
        <p className="max-w-prose text-[11px] leading-relaxed text-ink-500">
          Every knob has a sensible default, so you can jump straight to{" "}
          <b>Where to run</b> whenever you&apos;re ready.
        </p>
      </CardBody>
    </Card>
  );
}

function GroupStep({
  knobs, edits, current, onKnob,
}: {
  knobs: StudioKnob[];
  edits: Record<string, unknown>;
  current: Record<string, unknown>;
  onKnob: (path: string, value: unknown) => void;
}) {
  return (
    <Card>
      <CardBody className="space-y-2">
        {knobs.map((k) => (
          <KnobField
            key={k.path}
            knob={k}
            value={edits[k.path] ?? current[k.path]}
            changed={k.path in edits}
            baseValue={current[k.path]}
            onChange={(v) => onKnob(k.path, v)}
          />
        ))}
      </CardBody>
    </Card>
  );
}

function WizardNav({
  idx, total, onBack, onNext, onPreview,
}: {
  idx: number;
  total: number;
  onBack: () => void;
  onNext: () => void;
  onPreview: () => void;
}) {
  const isFirst = idx === 0;
  const isLast = idx === total - 1;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="secondary" onClick={onBack} disabled={isFirst}>
        <ChevronLeft size={14} /> Back
      </Button>
      <Button size="sm" variant="ghost" onClick={onPreview}>
        <Eye size={13} /> Preview YAML
      </Button>
      {!isLast ? (
        <Button size="sm" variant="secondary"
          className="ml-auto font-semibold text-accent-600 hover:text-accent" onClick={onNext}>
          Next <ChevronRight size={14} />
        </Button>
      ) : (
        <span className="ml-auto text-[11px] text-ink-500">
          Pick a target above, then launch.
        </span>
      )}
    </div>
  );
}

function LoadedRecipeBanner({
  recipe, onClear,
}: {
  recipe: StudioRecipe; onClear: () => void;
}) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
      <div className="flex items-center gap-2">
        <BookOpen size={14} className="text-amber-600" />
        <span className="text-sm font-bold text-ink">Loaded: {recipe.label}</span>
        {recipe.custom ? <Badge tone="info">yours</Badge> : (
          <Badge tone="muted">{recipe.category}</Badge>
        )}
        <button
          onClick={onClear}
          className="ml-auto text-[11px] font-semibold text-ink-500 hover:text-ink"
        >
          clear
        </button>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-ink-600">{recipe.description}</p>
      <p className="mt-1 text-[11px] text-ink-500">
        Estimated: {recipe.est_time}. Tweak anything below before launching.
      </p>
    </div>
  );
}

/* ────────────────────────── Local launch ────────────────────────── */

function LocalLaunch({
  catalog, method, edits, forceSmoke, launching, onLaunch,
}: {
  catalog: StudioCatalog;
  method: StudioMethod;
  edits: Record<string, unknown>;
  forceSmoke: boolean;
  launching: boolean;
  onLaunch: (body: {
    method: StudioMethod; smoke: boolean;
    recipe?: string | null; overrides?: Record<string, unknown>;
  }) => void;
}) {
  const gpuMissing = !catalog.gpu.available;
  return (
    <Card>
      <CardHeader className="text-sm font-bold flex items-center gap-2">
        <Server size={14} className="text-amber-600" /> Run on this machine
      </CardHeader>
      <CardBody className="space-y-3">
        <EnvGroupInstaller groupId="train" />
        {gpuMissing ? (
          <Banner tone="warn" icon={AlertTriangle}>
            No NVIDIA GPU detected: a full run will be very slow or fail. The
            smoke test still runs fine on CPU.
          </Banner>
        ) : null}
        <LaunchControls
          forceSmoke={forceSmoke}
          disabled={!catalog.dangerous_enabled || launching}
          launching={launching}
          onLaunch={(smoke) => onLaunch({ method, smoke, recipe: null, overrides: edits })}
        />
      </CardBody>
    </Card>
  );
}

/* ────────────────────────── Cloud launch ────────────────────────── */

function CloudLaunch({
  target, method, edits, loaded,
}: {
  target: CloudTarget;
  method: StudioMethod;
  edits: Record<string, unknown>;
  loaded: StudioRecipe | null;
}) {
  const [busy, setBusy] = React.useState(false);
  const [configPath, setConfigPath] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [values, setValues] = React.useState<Record<string, string>>({});

  const fields = target.fields ?? [];

  // Seed the form with each field's default, and reset when the target changes.
  React.useEffect(() => {
    const seed: Record<string, string> = {};
    for (const f of fields) seed[f.key] = f.default ?? "";
    setValues(seed);
    setConfigPath(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.id]);

  const missing = fields.filter((f) => !(values[f.key] ?? "").trim());
  const command = buildCommand(
    target.submit ?? "", configPath ?? "configs/train_studio.yaml", values);

  const prepare = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.trainMaterialize({ method, overrides: edits });
      setConfigPath(r.config_path);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true); window.setTimeout(() => setCopied(false), 1_400);
    } catch { /* clipboard unavailable */ }
  };

  return (
    <Card>
      <CardHeader className="text-sm font-bold flex items-center gap-2">
        <Cloud size={14} className="text-amber-600" /> Run on {target.label}
        <span className="font-normal text-[11px] text-ink-500">
          Puffin prepares the config and command; you run the submit yourself so
          it uses your own cloud credentials.
        </span>
      </CardHeader>
      <CardBody className="space-y-3">
        {/* Only the SDK this provider needs. */}
        <EnvGroupInstaller groupId={target.env_group} />
        {target.needs ? (
          <div className="text-[11px] text-ink-500">
            You&apos;ll also need: {target.needs}
          </div>
        ) : null}

        {/* Account details: filled into the submit command. */}
        {fields.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 rounded-xl border border-ink-200 bg-ink-50/50 p-3 sm:grid-cols-2">
            {fields.map((f) => (
              <label key={f.key} className="block space-y-1">
                <span className="text-xs font-semibold text-ink">{f.label}</span>
                <input
                  value={values[f.key] ?? ""}
                  placeholder={f.placeholder ?? f.default ?? ""}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  className="w-full rounded-lg border border-ink-200 bg-card px-2 py-1 text-xs
                             focus:border-accent focus:outline-none"
                />
                {f.help ? (
                  <span className="block text-[10px] leading-snug text-ink-500">{f.help}</span>
                ) : null}
              </label>
            ))}
          </div>
        ) : null}

        {/* Prepare + command */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" onClick={prepare} disabled={busy}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Sliders size={13} />}
            {configPath ? "Re-prepare config" : "Prepare launch"}
          </Button>
          {loaded ? (
            <span className="text-[11px] text-ink-500">
              from recipe <b>{loaded.label}</b>
            </span>
          ) : null}
          {target.docs ? (
            <a href={target.docs} target="_blank" rel="noreferrer"
               className="ml-auto inline-flex items-center gap-1 text-[11px] font-semibold text-accent-600 hover:underline">
              {target.label} docs <ExternalLink size={11} />
            </a>
          ) : null}
        </div>

        {err ? <Banner tone="fail" icon={AlertTriangle}>{err}</Banner> : null}

        {configPath ? (
          <div className="space-y-2">
            <div className="text-[11px] text-ink-500">
              Wrote <code>{configPath}</code>. Run this from the project root:
            </div>
            <div className="relative">
              <pre className="overflow-x-auto rounded-lg border border-ink-800/50 bg-[#0f172a]
                              p-3 pr-10 font-mono text-[11px] leading-relaxed text-slate-100">
                {command}
              </pre>
              <button
                type="button" onClick={copy} aria-label="Copy command"
                className="absolute right-2 top-2 rounded-md p-1.5 text-ink-400 hover:bg-white/10 hover:text-white"
              >
                {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
              </button>
            </div>
            {missing.length > 0 ? (
              <p className="flex items-start gap-1 text-[11px] leading-relaxed text-amber-700">
                <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                Fill in {missing.map((m) => m.label).join(", ")} above — the command
                shows &lt;{missing[0].key.toUpperCase()}&gt;-style placeholders until you do.
              </p>
            ) : (
              <p className="text-[10px] leading-relaxed text-ink-400">
                The job runs the same training entrypoint as a local run. Watch it
                in your cloud console.
              </p>
            )}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

/** Substitute {config} and each {field} token; empty fields become a visible
 *  <UPPER> placeholder so the command is obviously incomplete but still valid
 *  to copy and edit. */
function buildCommand(
  template: string, configPath: string, values: Record<string, string>,
): string {
  return template.replace(/\{(\w+)\}/g, (_m, key: string) => {
    if (key === "config") return configPath;
    const v = (values[key] ?? "").trim();
    return v || `<${key.toUpperCase()}>`;
  });
}

/* ────────────────────────── Recipe picker ────────────────────────── */

function RecipePickerModal({
  catalog, onPick, onClose, onRecipesChanged,
}: {
  catalog: StudioCatalog;
  onPick: (r: StudioRecipe) => void;
  onClose: () => void;
  onRecipesChanged: () => void;
}) {
  const [query, setQuery] = React.useState("");
  const [deleting, setDeleting] = React.useState<string | null>(null);

  const q = query.trim().toLowerCase();
  const matches = catalog.recipes.filter((r) =>
    !q || r.label.toLowerCase().includes(q) || r.description.toLowerCase().includes(q));
  const categories = catalog.recipe_categories.filter((c) =>
    matches.some((r) => r.category === c));

  const remove = async (id: string) => {
    setDeleting(id);
    try { await api.deleteRecipe(id); onRecipesChanged(); }
    finally { setDeleting(null); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
         onClick={onClose}>
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden
                      rounded-2xl border border-ink-200 bg-card shadow-card"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
          <BookOpen size={15} className="text-amber-600" />
          <span className="text-sm font-bold text-ink">Load a recipe</span>
          <span className="text-[11px] text-ink-400">
            a starting point you can tweak before launching
          </span>
          <button type="button" onClick={onClose} aria-label="Close"
            className="ml-auto rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink">
            <X size={15} />
          </button>
        </div>
        <div className="border-b border-ink-100 p-3">
          <div className="relative">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Search recipes"
              className="h-8 w-full rounded-lg border border-ink-200 bg-ink-50 pl-8 pr-2 text-xs
                         placeholder:text-ink-400 focus:border-accent focus:bg-card focus:outline-none"
            />
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
          {categories.map((cat) => (
            <div key={cat} className="space-y-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{cat}</div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {matches.filter((r) => r.category === cat).map((r) => {
                  const Icon = RECIPE_ICONS[r.icon] ?? Sliders;
                  return (
                    <div key={r.id}
                      className="group flex items-start gap-2 rounded-lg border border-ink-200
                                 bg-card px-3 py-2.5 text-left transition-all hover:border-accent hover:shadow-glow">
                      <button className="flex min-w-0 flex-1 items-start gap-2 text-left"
                        onClick={() => onPick(r)}>
                        <Icon size={15} className="mt-0.5 shrink-0 text-accent-600" />
                        <span className="min-w-0">
                          <span className="flex items-center gap-1.5">
                            <span className="text-[13px] font-bold text-ink">{r.label}</span>
                            <span className="rounded bg-ink-100 px-1 text-[8px] font-bold uppercase text-ink-500">
                              {r.method}
                            </span>
                          </span>
                          <span className="block text-[11px] leading-snug text-ink-500">{r.tagline}</span>
                        </span>
                      </button>
                      {r.custom ? (
                        <button type="button" onClick={() => remove(r.id)}
                          aria-label="Delete recipe"
                          className="shrink-0 rounded p-1 text-ink-400 opacity-0 hover:bg-ink-100 hover:text-red-600 group-hover:opacity-100">
                          {deleting === r.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          {matches.length === 0 ? (
            <div className="py-6 text-center text-xs text-ink-400">No recipes match “{query}”.</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────── Save recipe ────────────────────────── */

function SaveRecipeModal({
  method, overrides, onClose, onSaved,
}: {
  method: StudioMethod;
  overrides: Record<string, unknown>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState("");
  const [desc, setDesc] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const save = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      await api.saveRecipe({ name: name.trim(), method, overrides, description: desc.trim() });
      onSaved(); onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
         onClick={onClose}>
      <div className="w-full max-w-md space-y-3 rounded-2xl border border-ink-200 bg-card p-4 shadow-card"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <Save size={15} className="text-amber-600" />
          <span className="text-sm font-bold text-ink">Save as a recipe</span>
        </div>
        <p className="text-[11px] text-ink-500">
          Saves the {Object.keys(overrides).length} changed {method.toUpperCase()} setting(s)
          as a reusable preset in this project. It shows up under “Your recipes”.
        </p>
        <input
          autoFocus value={name} onChange={(e) => setName(e.target.value)}
          placeholder="Recipe name (e.g. Support-agent v2)"
          className="w-full rounded-lg border border-ink-200 px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none"
        />
        <textarea
          value={desc} onChange={(e) => setDesc(e.target.value)} rows={2}
          placeholder="What is this recipe for? (optional)"
          className="w-full resize-none rounded-lg border border-ink-200 px-2.5 py-1.5 text-xs focus:border-accent focus:outline-none"
        />
        {err ? (
          <div className="flex items-start gap-1.5 text-[11px] text-red-700">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {err}
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button size="sm" variant="primary" onClick={save} disabled={!name.trim() || busy}>
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save recipe
          </Button>
        </div>
      </div>
    </div>
  );
}

function KnobField({
  knob, value, changed, baseValue, onChange,
}: {
  knob: StudioKnob;
  value: unknown;
  changed: boolean;
  baseValue: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `knob-${knob.path.replace(/\./g, "-")}`;
  const oor = (knob.type === "int" || knob.type === "float")
    && typeof value === "number"
    && ((knob.min != null && value < knob.min)
        || (knob.max != null && value > knob.max));
  const bounds = [
    knob.min != null ? `min ${knob.min}` : null,
    knob.max != null ? `max ${knob.max}` : null,
  ].filter(Boolean).join(", ");
  return (
    <div className={cn(
      "rounded-lg -mx-2 px-2 py-1.5",
      changed && "bg-amber-50/70",
    )}>
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-sm font-semibold text-ink flex-1">
          {knob.label}
          {changed ? (
            <button
              className="ml-2 text-[10px] font-bold text-accent-600 uppercase"
              onClick={() => onChange(baseValue)}
              title="Reset to base config value"
            >
              reset
            </button>
          ) : null}
        </label>
        <KnobInput id={id} knob={knob} value={value} onChange={onChange} />
      </div>
      <p className="text-xs text-ink-500 mt-1 leading-relaxed">{knob.help}</p>
      {knob.option_help && Object.keys(knob.option_help).length ? (
        <ul className="mt-1.5 space-y-1">
          {Object.entries(knob.option_help).map(([opt, desc]) => (
            <li key={opt} className="flex gap-1.5 text-[11px] leading-snug text-ink-500">
              <code className="mt-px h-fit shrink-0 rounded bg-ink-100 px-1 font-mono text-[10px] text-ink-700">
                {opt}
              </code>
              <span>{desc}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {knob.recommended ? (
        <p className="mt-1.5 flex items-start gap-1.5 rounded-md bg-amber-50/70 px-2 py-1
                      text-[11px] leading-snug text-amber-900">
          <span className="shrink-0 font-bold">Ideal:</span>
          <span>{knob.recommended}</span>
        </p>
      ) : null}
      {oor ? (
        <p className="mt-1 flex items-start gap-1 text-[11px] font-medium text-amber-700">
          <AlertTriangle size={11} className="mt-0.5 shrink-0" />
          Outside the recommended range ({bounds}). Fine to override if you know why.
        </p>
      ) : null}
    </div>
  );
}

function KnobInput({
  id, knob, value, onChange,
}: {
  id: string;
  knob: StudioKnob;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const base = "border border-ink-200 rounded-lg text-sm px-2 py-1 bg-card";
  if (knob.type === "bool") {
    return (
      <input
        id={id} type="checkbox"
        className="w-4 h-4 accent-amber-500"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }
  if (knob.type === "select") {
    return (
      <select
        id={id}
        className={cn(base, "max-w-[200px]")}
        value={String(value ?? knob.options?.[0] ?? "")}
        onChange={(e) => onChange(e.target.value)}
      >
        {(knob.options ?? []).map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    );
  }
  if (knob.type === "int" || knob.type === "float") {
    return (
      <input
        id={id} type="number"
        className={cn(base, "w-32 text-right")}
        value={value === undefined || value === null ? "" : String(value)}
        min={knob.min} max={knob.max}
        step={knob.type === "int" ? knob.step ?? 1 : "any"}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return onChange(undefined);
          const n = knob.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
          if (!Number.isNaN(n)) onChange(n);
        }}
      />
    );
  }
  const isBaseModel = knob.path === "model.base_model";
  return (
    <>
      <input
        id={id} type="text"
        className={cn(base, "w-64")}
        value={String(value ?? "")}
        placeholder="e.g. meta-llama/Llama-3.1-8B-Instruct"
        list={isBaseModel ? "base-model-suggestions" : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {isBaseModel ? (
        <datalist id="base-model-suggestions">
          {BASE_MODEL_SUGGESTIONS.map((m) => <option key={m} value={m} />)}
        </datalist>
      ) : null}
    </>
  );
}

/* ────────────────────────── Shared pieces ────────────────────────── */

function LaunchControls({
  forceSmoke, disabled, launching, onLaunch,
}: {
  forceSmoke: boolean;
  disabled: boolean;
  launching: boolean;
  onLaunch: (smoke: boolean) => void;
}) {
  const [confirmFull, setConfirmFull] = React.useState(false);
  React.useEffect(() => {
    if (!confirmFull) return;
    const t = setTimeout(() => setConfirmFull(false), 4000);
    return () => clearTimeout(t);
  }, [confirmFull]);

  return (
    <div className="flex flex-wrap items-center gap-2 pt-1">
      <Button
        variant="primary"
        disabled={disabled}
        onClick={() => onLaunch(true)}
      >
        <Zap size={14} />
        {launching ? "Launching…" : "Run smoke test"}
      </Button>
      {!forceSmoke ? (
        <Button
          variant={confirmFull ? "danger" : "secondary"}
          disabled={disabled}
          onClick={() => {
            if (confirmFull) {
              setConfirmFull(false);
              onLaunch(false);
            } else {
              setConfirmFull(true);
            }
          }}
        >
          {confirmFull ? "Click again to confirm" : "Start full training"}
        </Button>
      ) : null}
      <span className="text-[11px] text-ink-500">
        {forceSmoke
          ? "This recipe always runs as a smoke test."
          : "Smoke test: ~1 min, tiny model, catches problems before you pay for GPU time."}
      </span>
    </div>
  );
}

function LaunchResultCard({
  result, lastBody, launching, onRelaunch,
}: {
  result: TrainLaunchResult;
  lastBody: LaunchBody | null;
  launching: boolean;
  onRelaunch: (smoke: boolean) => void;
}) {
  const l = result.launch;
  const failed = l.kind === "error";
  const [open, setOpen] = React.useState(false);
  const wasSmoke = Boolean(lastBody?.smoke);
  return (
    <Card>
      <CardHeader className="flex items-center gap-2">
        <Badge tone={failed ? "fail" : "ok"}>
          {failed ? "Launch blocked" : "Training started"}
        </Badge>
        {!failed && l.pid ? (
          <span className="text-xs text-ink-500">PID {l.pid}</span>
        ) : null}
      </CardHeader>
      <CardBody className="space-y-3">
        <p className="text-sm text-ink-700">{l.message}</p>
        {!failed ? (
          <div className="text-xs text-ink-500 space-y-0.5">
            <div>Adapter: <code>{l.adapter_dir}</code></div>
            <div>Log: <code>{l.log_path}</code></div>
            <div>Config: <code>{result.config_path}</code></div>
          </div>
        ) : null}

        {/* Close the loop: promote a passing smoke to a full run, or re-run
            the exact same config, without reconfiguring. */}
        {!failed && lastBody ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3">
            {wasSmoke ? (
              <>
                <Button size="sm" variant="primary"
                  disabled={launching} onClick={() => onRelaunch(false)}>
                  <Flame size={13} /> Run full training with these settings
                </Button>
                <span className="text-[11px] text-ink-500">
                  Smoke launched. Once it passes, promote it to a real run.
                </span>
              </>
            ) : (
              <Button size="sm" variant="secondary"
                disabled={launching} onClick={() => onRelaunch(false)}>
                <RotateCcw size={13} /> Re-run this config
              </Button>
            )}
          </div>
        ) : null}

        {!failed && l.adapter_dir ? (
          <TrainingLogPanel adapterDir={l.adapter_dir} live tail={400} />
        ) : null}

        <button
          className="flex items-center gap-1 text-xs font-semibold text-ink-500 hover:text-ink"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          Materialized config
        </button>
        {open ? (
          <pre className="text-[11px] leading-relaxed bg-ink-50 border border-ink-200 rounded-lg p-3 overflow-x-auto max-h-80 overflow-y-auto">
            {result.yaml}
          </pre>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Segmented({
  options, value, onChange,
}: {
  options: Array<{ key: string; label: string }>;
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-ink-200 bg-ink-50 p-0.5">
      {options.map((o) => (
        <button
          key={o.key}
          onClick={() => onChange(o.key)}
          className={cn(
            "px-3 py-1 text-xs font-semibold rounded-md transition-colors",
            o.key === value
              ? "bg-card text-ink shadow-card"
              : "text-ink-500 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function GpuChip({ gpu }: { gpu: StudioCatalog["gpu"] }) {
  return gpu.available ? (
    <Badge tone="ok">
      <Cpu size={11} /> {gpu.name} · {gpu.vram_total_gb} GB
    </Badge>
  ) : (
    <Badge tone="muted"><Cpu size={11} /> CPU only</Badge>
  );
}

function Banner({
  tone, icon: Icon, children,
}: {
  tone: "warn" | "fail";
  icon: typeof AlertTriangle;
  children: React.ReactNode;
}) {
  return (
    <div className={cn(
      "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm",
      tone === "warn"
        ? "bg-amber-50 border-amber-200 text-amber-900"
        : "bg-red-50 border-red-200 text-red-900",
    )}>
      <Icon size={15} className="mt-0.5 shrink-0" />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
}
