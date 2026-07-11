"use client";
/**
 * Project overview: a small, persistent design doc (goal, audience, desired
 * behavior, data, success criteria, constraints). Saved to
 * configs/project_brief.yaml and injected into the AI assistant's context on
 * every page, so the whole project works toward one stated intent.
 */
import * as React from "react";
import useSWR from "swr";
import { CheckCircle2, Compass, Loader2, Save } from "@/components/ui/icons";
import { api } from "@/lib/api";
import type { ProjectBrief } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { AskAIButton } from "@/components/ai/AskAI";
import { cn } from "@/lib/cn";

const META: Record<string, { placeholder: string; rows: number; hint?: string }> = {
  title: { placeholder: "e.g. Customer-support assistant v2", rows: 1 },
  goal: { placeholder: "What is this fine-tune for? What problem does it solve, and why now?", rows: 3 },
  audience: { placeholder: "Who will use the model? End users, an internal team, an API integration...", rows: 2 },
  desired_behavior: { placeholder: "How should it respond? Tone, format, what it must always / never do.", rows: 4 },
  data: { placeholder: "What data do you have or need? Sources, shape (chat / pairs / prompts), rough volume.", rows: 3 },
  success: { placeholder: "How will you know it's good? Metrics, the eval cases that matter, the bar to ship.", rows: 3 },
  constraints: { placeholder: "Safety rules, latency / cost limits, topics that are out of scope.", rows: 3 },
};

export default function OverviewPage() {
  const { data, mutate } = useSWR<ProjectBrief>("brief", () => api.getBrief());
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const [saving, setSaving] = React.useState(false);
  const [savedAt, setSavedAt] = React.useState<string | null>(null);
  const seeded = React.useRef(false);

  React.useEffect(() => {
    if (data && !seeded.current) {
      setDraft(data.fields);
      seeded.current = true;
    }
  }, [data]);

  const labels = data?.labels ?? {};
  const keys = Object.keys(labels);
  const dirty = data ? keys.some((k) => (draft[k] ?? "") !== (data.fields[k] ?? "")) : false;
  const filled = keys.filter((k) => (draft[k] ?? "").trim() !== "").length;

  // Consistent width rhythm: long-form fields span full width and lead; the
  // remaining short answers pair two-up. Rendering full fields first (then the
  // halves) guarantees clean rows with no orphaned half beside a full field.
  const isFull = (k: string) => k === "title" || k === "goal" || k === "desired_behavior";
  const fullKeys = keys.filter(isFull);
  const halfKeys = keys.filter((k) => !isFull(k));
  const ordered = [...fullKeys, ...halfKeys];
  // If the short-answer count is odd, the last one goes full-width so the
  // right edge never ends ragged.
  const halfOrphan = halfKeys.length % 2 === 1 ? halfKeys[halfKeys.length - 1] : null;

  const set = (k: string, v: string) => setDraft((p) => ({ ...p, [k]: v }));
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.saveBrief(draft);
      await mutate(r, { revalidate: false });
      setSavedAt(new Date().toLocaleTimeString());
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-extrabold text-ink flex items-center gap-2">
            <Compass size={22} className="text-amber-600" /> Project overview
          </h1>
          <p className="text-sm text-ink-500 mt-1 max-w-prose">
            The design doc for this fine-tune. Fill it in once; the AI assistant
            reads it on every page, and it keeps the data, training, and eval work
            pointed at the same goal.
          </p>
        </div>
        <AskAIButton
          variant={filled === 0 ? "primary" : "secondary"}
          prompt="Interview me briefly to fill in the project brief (goal, audience, desired behavior, data, success criteria, constraints), then propose values for each field so I can save them on the Overview page.">
          Draft with AI
        </AskAIButton>
      </div>

      <Card>
        <CardHeader className="sticky top-0 z-10 flex flex-wrap items-center gap-2 bg-card text-sm font-bold">
          Design brief
          {keys.length ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-normal text-ink-500">
              <span className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-100">
                <span className="block h-full rounded-full bg-accent transition-all"
                  style={{ width: `${Math.round((filled / keys.length) * 100)}%` }} />
              </span>
              <span className="tabular-nums font-semibold">{filled}/{keys.length}</span> filled
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {savedAt && !dirty ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
                <CheckCircle2 size={12} /> saved {savedAt}
              </span>
            ) : null}
            <Button size="sm" variant="primary" onClick={() => void save()}
              disabled={saving || !dirty}>
              {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
              Save brief
            </Button>
          </div>
        </CardHeader>
        <CardBody className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {keys.length === 0 ? (
            <div className="text-sm text-ink-500 sm:col-span-2">Loading…</div>
          ) : ordered.map((k) => {
            const meta = META[k] ?? { placeholder: "", rows: 2 };
            // Long-form fields (+ any odd short field) span full width; the rest
            // pair two-per-row so the brief reads as a compact, even-edged form.
            const full = isFull(k) || k === halfOrphan;
            return (
              <label key={k} className={cn("block space-y-1", full && "sm:col-span-2")}>
                <span className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                  {labels[k]}
                  {(draft[k] ?? "").trim() ? (
                    <CheckCircle2 size={12} className="text-emerald-500" />
                  ) : null}
                </span>
                {k === "title" ? (
                  <input
                    // eslint-disable-next-line jsx-a11y/no-autofocus
                    autoFocus
                    value={draft[k] ?? ""} onChange={(e) => set(k, e.target.value)}
                    placeholder={meta.placeholder}
                    className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm
                               focus:border-accent focus:outline-none"
                  />
                ) : (
                  <textarea
                    value={draft[k] ?? ""} onChange={(e) => set(k, e.target.value)}
                    rows={meta.rows} placeholder={meta.placeholder}
                    className="w-full resize-y rounded-lg border border-ink-200 px-3 py-2 text-sm
                               leading-relaxed focus:border-accent focus:outline-none"
                  />
                )}
              </label>
            );
          })}
        </CardBody>
      </Card>
    </div>
  );
}
