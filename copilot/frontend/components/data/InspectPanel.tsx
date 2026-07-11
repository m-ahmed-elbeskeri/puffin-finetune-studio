"use client";
import * as React from "react";
import useSWR from "swr";
import { AlertCircle, AlertTriangle, BadgeCheck, Braces, ChevronLeft, ChevronRight, Fingerprint, Gauge, Loader2, Play, ScanSearch, ShieldCheck, ShieldAlert, Sparkles } from "@/components/ui/icons";
import {
  api, type DataQualityReport, type TemplatePreview, type TokenReport,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/lib/stores/uiStore";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

interface DataFile {
  path: string; name: string; kind: string;
  size_bytes: number; mtime: string; line_count: number;
  schema_hint: string;
}

function num(n: number | undefined | null): string {
  return (n ?? 0).toLocaleString();
}

/**
 * The "trust your data" surface. Everything here is read-only analysis a
 * fine-tuning engineer runs before spending GPU time: token budget,
 * what the model actually sees (chat template + loss mask), split leakage,
 * response quality, and a reproducibility fingerprint.
 */
export function InspectPanel({
  raw, processed,
}: {
  raw: DataFile[];
  processed: DataFile[];
}) {
  const files = [...processed, ...raw];
  const preferred = processed.find((f) => f.name === "train.jsonl") ?? files[0];
  const [path, setPath] = React.useState(preferred?.path ?? "");

  React.useEffect(() => {
    if (!path && preferred) setPath(preferred.path);
  }, [preferred, path]);

  if (files.length === 0) {
    return (
      <Card>
        <CardBody className="flex items-center gap-2 text-sm text-ink-500">
          <ScanSearch size={15} className="text-ink-400" />
          Add data first, then inspect it here before training.
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardBody className="space-y-3">
          <p className="rounded-lg bg-ink-50 px-3 py-2 text-[11px] leading-relaxed text-ink-600">
            This is where you decide whether the data is worth training on. Chars
            are a poor proxy, so token counts use your real base-model tokenizer;
            the chat-template view shows exactly what the model reads and which
            words it is scored on; and the leakage check protects your eval
            numbers from contamination. Nothing here changes your files.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
              Inspect file
            </span>
            <select
              value={path}
              onChange={(e) => setPath(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-ink-200 bg-card px-2 py-1.5
                         font-mono text-xs focus:border-accent focus:outline-none sm:flex-none"
            >
              {files.map((f) => (
                <option key={f.path} value={f.path}>
                  {f.path} ({f.line_count.toLocaleString()} records)
                </option>
              ))}
            </select>
          </div>
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <TokenCard path={path} />
        <QualityCard path={path} />
      </div>
      <TemplateCard path={path} />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <LeakageCard hasSplits={processed.some((f) => f.line_count > 0)} />
        <FingerprintCard />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* small shared bits                                                   */
/* ------------------------------------------------------------------ */

function Tile({
  label, value, tone, sub,
}: {
  label: string; value: React.ReactNode;
  tone?: "ok" | "warn" | "fail"; sub?: string;
}) {
  return (
    <div className={cn(
      "rounded-lg border bg-card p-2.5",
      tone === "ok" && "border-l-4 border-l-emerald-500 border-ink-200",
      tone === "warn" && "border-l-4 border-l-amber-500 border-ink-200",
      tone === "fail" && "border-l-4 border-l-red-500 border-ink-200",
      !tone && "border-ink-200",
    )}>
      <div className="text-[9px] font-bold uppercase tracking-wider text-ink-500">{label}</div>
      <div className="mt-0.5 text-lg font-extrabold tabular-nums text-ink">{value}</div>
      {sub ? <div className="text-[10px] text-ink-500">{sub}</div> : null}
    </div>
  );
}

function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1">
      {items.map((w) => (
        <div key={w} className="flex items-start gap-1.5 rounded-md bg-amber-50 px-2 py-1.5
                                text-[11px] text-amber-900">
          <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-600" />
          {w}
        </div>
      ))}
    </div>
  );
}

function CardShell({
  icon: Icon, title, hint, children,
}: {
  icon: typeof Gauge; title: string; hint: string; children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex items-center gap-2 text-sm font-bold">
        <Icon size={14} className="text-amber-600" />
        {title}
        <span className="font-normal text-[10px] text-ink-500">{hint}</span>
      </CardHeader>
      <CardBody className="space-y-3">{children}</CardBody>
    </Card>
  );
}

function LazyBlock({
  onRun, running, ran, label, children,
}: {
  onRun: () => void; running: boolean; ran: boolean;
  label: string; children: React.ReactNode;
}) {
  if (ran) return <>{children}</>;
  return (
    <button
      type="button"
      onClick={onRun}
      disabled={running}
      className="flex w-full items-center justify-center gap-2 rounded-lg border
                 border-dashed border-ink-200 py-4 text-xs font-semibold text-ink-500
                 transition-colors hover:border-accent hover:text-ink disabled:opacity-60"
    >
      {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
      {running ? "Analyzing…" : label}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Tokens                                                              */
/* ------------------------------------------------------------------ */

function TokenCard({ path }: { path: string }) {
  const [ran, setRan] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [data, setData] = React.useState<TokenReport | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => { setRan(false); setData(null); setErr(null); }, [path]);

  const run = async () => {
    setRunning(true); setErr(null);
    try {
      setData(await api.inspectTokens(path));
      setRan(true);
    } catch (e) { setErr((e as Error).message); }
    finally { setRunning(false); }
  };

  const pct = data ? Math.min(100, Math.round(100 * data.tokens.p99 / data.max_seq_length)) : 0;

  return (
    <CardShell icon={Gauge} title="Token budget"
      hint="real tokenizer, not character counts">
      {err ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {err}
        </div>
      ) : null}
      <LazyBlock onRun={run} running={running} ran={ran && !!data}
        label="Count tokens with the base-model tokenizer">
        {data ? (
          <>
            <div className="flex items-center gap-1.5 text-[10px] text-ink-500">
              {data.exact
                ? <BadgeCheck size={11} className="text-emerald-600" />
                : <AlertTriangle size={11} className="text-amber-600" />}
              {data.exact
                ? <>tokenizer: <code className="text-ink-700">{data.tokenizer}</code></>
                : <>estimated (tokenizer unavailable, ~4 chars/token)</>}
              <span className="ml-auto">sampled {num(data.sampled)} of {num(data.total_records)}</span>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Tile label="median" value={num(data.tokens.p50)} sub="tokens/record" />
              <Tile label="p90" value={num(data.tokens.p90)} />
              <Tile label="p99" value={num(data.tokens.p99)} />
              <Tile label="max" value={num(data.tokens.max)}
                tone={data.tokens.max > data.max_seq_length ? "warn" : undefined} />
            </div>
            {/* budget bar vs max_seq_length */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-[10px] text-ink-500">
                <span>p99 vs max_seq_length ({num(data.max_seq_length)})</span>
                <span className="tabular-nums">{pct}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-ink-100">
                <div className={cn("h-full", pct >= 100 ? "bg-red-500" : pct > 80 ? "bg-amber-500" : "bg-teal")}
                  style={{ width: `${pct}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Tile label="over max_seq" value={`${data.over_max_seq_pct}%`}
                sub="truncated during training"
                tone={data.over_max_seq_pct > 0 ? "warn" : "ok"} />
              <Tile label="tokens / epoch" value={compact(data.est_tokens_per_epoch)}
                sub={`~$${data.est_cost_per_epoch_usd} est. compute`} />
            </div>
            <Warnings items={data.warnings} />
          </>
        ) : null}
      </LazyBlock>
    </CardShell>
  );
}

function compact(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

/* ------------------------------------------------------------------ */
/* Quality                                                             */
/* ------------------------------------------------------------------ */

function QualityCard({ path }: { path: string }) {
  const { data, error, isLoading } = useSWR(
    path ? `inspect:quality:${path}` : null, () => api.inspectQuality(path));

  return (
    <CardShell icon={ScanSearch} title="Response quality"
      hint="what the labels actually teach">
      {isLoading ? (
        <div className="flex items-center gap-2 py-4 text-xs text-ink-500">
          <Loader2 size={13} className="animate-spin" /> Scanning records…
        </div>
      ) : error ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {String(error)}
        </div>
      ) : data ? <QualityBody data={data} /> : null}
    </CardShell>
  );
}

function QualityBody({ data }: { data: DataQualityReport }) {
  if (data.total_records === 0) {
    return <div className="text-xs text-ink-500">This file is empty.</div>;
  }
  const clean = data.warnings.length === 0;
  return (
    <>
      <div className="flex items-center gap-1.5 text-[10px] text-ink-500">
        <span className="rounded bg-ink-100 px-1.5 py-0.5 font-bold text-ink-600">
          {data.schema === "preference" ? "preference (DPO)" : "chat / messages"}
        </span>
        <span className="ml-auto">sampled {num(data.sampled)} of {num(data.total_records)}</span>
      </div>
      {data.schema === "preference" ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Tile label="identical pairs" value={num(data.identical_pairs)}
            tone={data.identical_pairs ? "warn" : "ok"} />
          <Tile label="missing side" value={num(data.empty_side)}
            tone={data.empty_side ? "warn" : "ok"} />
          <Tile label="chosen longer" value={`${Math.round((data.chosen_longer_frac ?? 0) * 100)}%`}
            tone={(data.chosen_longer_frac ?? 0) > 0.8 ? "warn" : undefined}
            sub="length-bias risk" />
          <Tile label="chosen chars" value={num(data.mean_chosen_chars)} sub="mean" />
          <Tile label="rejected chars" value={num(data.mean_rejected_chars)} sub="mean" />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Tile label="empty replies" value={num(data.empty_assistant)}
            tone={data.empty_assistant ? "fail" : "ok"} />
          <Tile label="no assistant" value={num(data.no_assistant)}
            tone={data.no_assistant ? "fail" : "ok"} />
          <Tile label="bad alternation" value={num(data.bad_alternation)}
            tone={data.bad_alternation ? "warn" : "ok"} />
          <Tile label="refusal rate" value={`${Math.round((data.refusal_rate ?? 0) * 100)}%`}
            tone={(data.refusal_rate ?? 0) > 0.15 ? "warn" : undefined} />
          <Tile label="turns" value={`${num(data.single_turn)}/${num(data.multi_turn)}`}
            sub="single / multi" />
          <Tile label="system prompts" value={num(data.distinct_system_prompts)}
            sub={`${num(data.with_system)} with system`} />
        </div>
      )}
      {clean ? (
        <div className="flex items-center gap-1.5 rounded-md bg-emerald-50 px-2 py-1.5
                        text-[11px] font-semibold text-emerald-800">
          <BadgeCheck size={12} /> No quality issues found in the sample.
        </div>
      ) : <Warnings items={data.warnings} />}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Chat template + loss mask                                           */
/* ------------------------------------------------------------------ */

function TemplateCard({ path }: { path: string }) {
  const [index, setIndex] = React.useState(0);
  const [ran, setRan] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [data, setData] = React.useState<TemplatePreview | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => { setRan(false); setData(null); setErr(null); setIndex(0); }, [path]);

  const load = async (i: number) => {
    setRunning(true); setErr(null);
    try {
      setData(await api.inspectTemplate(path, i));
      setRan(true);
    } catch (e) { setErr((e as Error).message); }
    finally { setRunning(false); }
  };

  const step = (delta: number) => {
    const next = Math.max(0, index + delta);
    setIndex(next);
    void load(next);
  };

  return (
    <CardShell icon={Braces} title="What the model sees"
      hint="chat template + which words are trained on">
      {err ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {err}
        </div>
      ) : null}
      <LazyBlock onRun={() => load(0)} running={running} ran={ran && !!data}
        label="Render one record through the chat template">
        {data ? (
          <>
            <div className="flex items-center gap-2 text-[11px] text-ink-500">
              <button type="button" onClick={() => step(-1)} disabled={index === 0 || running}
                className="rounded p-1 hover:bg-ink-100 disabled:opacity-30" aria-label="Previous record">
                <ChevronLeft size={14} />
              </button>
              record #{data.index}
              <button type="button" onClick={() => step(1)} disabled={running}
                className="rounded p-1 hover:bg-ink-100 disabled:opacity-40" aria-label="Next record">
                <ChevronRight size={14} />
              </button>
              <span className="ml-auto flex items-center gap-2">
                {data.token_count != null ? <span>{num(data.token_count)} tokens</span> : null}
                <span>{Math.round(data.trained_fraction * 100)}% trained</span>
              </span>
            </div>

            {/* legend */}
            <div className="flex items-center gap-3 text-[10px] text-ink-500">
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm border border-amber-300 bg-amber-100" />
                trained (assistant)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm border border-ink-200 bg-ink-50" />
                context only (masked)
              </span>
            </div>

            {/* segment view */}
            <div className="space-y-1.5">
              {data.segments.map((s, i) => (
                <div key={i} className={cn(
                  "rounded-lg border px-2.5 py-1.5",
                  s.trained ? "border-amber-300 bg-amber-50" : "border-ink-200 bg-ink-50",
                )}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] font-bold uppercase tracking-wider text-ink-400">
                      {s.role}
                    </span>
                    {s.trained ? (
                      <span className="rounded bg-amber-200 px-1 text-[8px] font-bold text-amber-800">
                        TRAINED
                      </span>
                    ) : (
                      <span className="rounded bg-ink-200 px-1 text-[8px] font-bold text-ink-500">
                        MASKED
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 whitespace-pre-wrap break-words text-[12px] text-ink-800">
                    {s.content || <span className="text-ink-400">(empty)</span>}
                  </div>
                </div>
              ))}
            </div>

            {data.rendered ? (
              <details className="text-[11px]">
                <summary className="cursor-pointer font-semibold text-ink-500">
                  Raw rendered string (with special tokens)
                </summary>
                <pre className="mt-1 max-h-52 overflow-auto rounded-lg border border-ink-800/50
                                bg-[#0f172a] p-2.5 font-mono text-[11px] text-slate-100">
                  {data.rendered}
                </pre>
              </details>
            ) : (
              <div className="text-[10px] text-ink-400">
                Tokenizer unavailable, so the raw rendered string is hidden; the
                segment breakdown above still shows the loss mask.
              </div>
            )}
            <p className="text-[10px] leading-relaxed text-ink-500">{data.note}</p>
          </>
        ) : null}
      </LazyBlock>
    </CardShell>
  );
}

/* ------------------------------------------------------------------ */
/* Leakage                                                             */
/* ------------------------------------------------------------------ */

function LeakageCard({ hasSplits }: { hasSplits: boolean }) {
  const openDrawer = useUiStore((s) => s.openDrawer);
  const { data, error, isLoading } = useSWR(
    hasSplits ? "inspect:leakage" : null, () => api.inspectLeakage());

  return (
    <CardShell icon={data?.present && !data.clean ? ShieldAlert : ShieldCheck}
      title="Split leakage" hint="contamination inflates eval scores">
      {!hasSplits ? (
        <div className="text-xs text-ink-500">
          Build your train / eval / test splits first, then this checks them for
          overlap.
        </div>
      ) : isLoading ? (
        <div className="flex items-center gap-2 py-4 text-xs text-ink-500">
          <Loader2 size={13} className="animate-spin" /> Comparing splits…
        </div>
      ) : error ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {String(error)}
        </div>
      ) : data && data.present ? (
        <>
          {data.clean ? (
            <div className="flex items-center gap-1.5 rounded-md bg-emerald-50 px-2 py-1.5
                            text-[11px] font-semibold text-emerald-800">
              <ShieldCheck size={12} /> No overlap found. Your eval numbers will be honest.
            </div>
          ) : (
            <div className="flex items-center gap-1.5 rounded-md bg-red-50 px-2 py-1.5
                            text-[11px] font-semibold text-red-800">
              <ShieldAlert size={12} /> Overlap found: eval scores may be inflated.
            </div>
          )}
          <div className="overflow-hidden rounded-lg border border-ink-200">
            <table className="w-full text-[11px]">
              <thead className="bg-ink-50 text-[9px] uppercase tracking-wider text-ink-500">
                <tr>
                  <th className="px-2 py-1 text-left font-bold">between</th>
                  <th className="px-2 py-1 text-right font-bold">identical</th>
                  <th className="px-2 py-1 text-right font-bold">same prompt</th>
                </tr>
              </thead>
              <tbody>
                {data.pairs.map((p) => (
                  <tr key={`${p.a}-${p.b}`} className="border-t border-ink-100">
                    <td className="px-2 py-1 font-mono">{p.a} + {p.b}</td>
                    <td className={cn("px-2 py-1 text-right tabular-nums font-bold",
                      p.exact_overlap ? "text-red-700" : "text-ink-400")}>
                      {p.exact_overlap}
                    </td>
                    <td className={cn("px-2 py-1 text-right tabular-nums font-bold",
                      p.prompt_overlap ? "text-amber-700" : "text-ink-400")}>
                      {p.prompt_overlap}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.examples && data.examples.length > 0 ? (
            <details className="text-[11px]">
              <summary className="cursor-pointer font-semibold text-ink-500">
                Example overlapping records
              </summary>
              <div className="mt-1 space-y-1">
                {data.examples.map((ex, i) => (
                  <div key={i} className="rounded bg-ink-50 px-2 py-1">
                    <span className="text-[9px] font-bold uppercase text-ink-400">{ex.kind}: </span>
                    <span className="text-ink-700">{ex.text}</span>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
          {!data.clean ? (
            <button
              type="button"
              onClick={() => openDrawer(
                "My splits have leakage between train and eval. Explain why this "
                + "inflates my eval scores and write a transform script that removes "
                + "any training record whose prompt also appears in the eval or test split.")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-ink-200
                         bg-card px-2.5 py-1.5 text-[11px] font-semibold text-ink-600
                         hover:border-accent hover:text-ink"
            >
              <Sparkles size={11} className="text-amber-500" /> Fix it with AI
            </button>
          ) : null}
        </>
      ) : (
        <div className="text-xs text-ink-500">{data?.message}</div>
      )}
    </CardShell>
  );
}

/* ------------------------------------------------------------------ */
/* Fingerprint + lineage                                               */
/* ------------------------------------------------------------------ */

function FingerprintCard() {
  const { data, error, isLoading } = useSWR(
    "inspect:fingerprint", () => api.inspectFingerprint());

  return (
    <CardShell icon={Fingerprint} title="Version & lineage"
      hint="pin a training run to exact data">
      {isLoading ? (
        <div className="flex items-center gap-2 py-4 text-xs text-ink-500">
          <Loader2 size={13} className="animate-spin" /> Hashing splits…
        </div>
      ) : error ? (
        <div className="flex items-start gap-1.5 text-xs text-red-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {String(error)}
        </div>
      ) : data ? (
        !data.built ? (
          <div className="text-xs text-ink-500">
            No splits yet. Once you build them, this gives each a content hash so a
            training run can be tied to the exact data that produced it.
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
                dataset
              </span>
              <code className="rounded bg-[#0f1c2e] px-1.5 py-0.5 font-mono text-[11px]
                               font-bold text-[#f0a184]">
                {data.dataset_hash}
              </code>
            </div>
            <div className="overflow-hidden rounded-lg border border-ink-200">
              <table className="w-full text-[11px]">
                <tbody>
                  {Object.entries(data.splits).map(([name, s]) => (
                    <tr key={name} className="border-t border-ink-100 first:border-t-0">
                      <td className="px-2 py-1 font-semibold">{name}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-ink-500">
                        {s.records.toLocaleString()} rec
                      </td>
                      <td className="px-2 py-1 text-right font-mono text-ink-400">{s.sha256}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="space-y-1 text-[11px] text-ink-600">
              <div>
                <span className="font-bold text-ink-500">sources: </span>
                {data.lineage.sources.length
                  ? data.lineage.sources.join(", ")
                  : <span className="text-ink-400">none</span>}
              </div>
              <div>
                <span className="font-bold text-ink-500">transforms: </span>
                {data.lineage.transforms.length
                  ? data.lineage.transforms.join(" then ")
                  : <span className="text-ink-400">none</span>}
              </div>
              <div>
                <span className="font-bold text-ink-500">split: </span>
                {data.lineage.split.train != null
                  ? `${Math.round(data.lineage.split.train * 100)}/${Math.round((data.lineage.split.eval ?? 0) * 100)}/${Math.round((data.lineage.split.test ?? 0) * 100)}, seed ${data.lineage.split.seed}`
                  : <span className="text-ink-400">default</span>}
              </div>
            </div>
            <p className="text-[10px] leading-relaxed text-ink-500">
              Record this hash with a training run. If the data changes, the hash
              changes, so you always know exactly what a model was trained on.
            </p>
          </>
        )
      ) : null}
    </CardShell>
  );
}
