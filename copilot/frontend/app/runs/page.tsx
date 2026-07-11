"use client";
import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, FlaskConical } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { RunHistoryCard } from "@/components/artifacts/RunHistoryCard";
import { RunDetailCard } from "@/components/artifacts/RunDetailCard";
import { LiveTrainingCard } from "@/components/artifacts/LiveTrainingCard";
import { TrainingLogPanel } from "@/components/train/TrainingLogPanel";
import { RunConfigPanel } from "@/components/train/RunConfigPanel";
import { useLiveTraining } from "@/lib/hooks/useLiveTraining";

export default function RunsPage() {
  const live = useLiveTraining();
  const { data: history } = useSWR("runs", () => api.runs(),
    { refreshInterval: 5_000 });
  const runs = history?.runs ?? [];
  const [picked, setPicked] = React.useState<string | null>(null);

  // Default to the newest run
  React.useEffect(() => {
    if (!picked && runs.length > 0) {
      setPicked(runs[0].adapter_dir);
    }
  }, [picked, runs]);

  const { data: detail } = useSWR(
    picked ? ["run", picked] : null,
    () => api.run(picked!),
  );

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-extrabold text-ink">Training runs</h1>
          <p className="text-sm text-ink-500 mt-1">
            Every past + active run. Click a row to inspect.
          </p>
        </div>
      </div>

      {live?.active ? (
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
            Live
          </div>
          <LiveTrainingCard data={live} />
          {live.run?.adapter_dir ? (
            <TrainingLogPanel
              adapterDir={live.run.adapter_dir} live defaultOpen tail={1000} />
          ) : null}
        </div>
      ) : null}

      {history ? (
        <div onClick={(e) => {
          // Capture row clicks by adapter_dir from the data attribute.
          const tr = (e.target as HTMLElement).closest("tr[data-run]");
          const dir = tr?.getAttribute("data-run");
          if (dir) setPicked(dir);
        }}>
          {/* Inline the table with selection hooked up */}
          <RunHistoryCard data={history} />
        </div>
      ) : null}

      {detail ? (
        <>
          <RunDetailCard data={detail} />

          {/* Next step: a good finished adapter is ready to evaluate. */}
          {detail.run.status === "completed" && !detail.run.smoke_test ? (
            <div className="flex flex-wrap items-center gap-2">
              <Link href="/evaluate"
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5
                           text-xs font-semibold text-ink-50 transition-colors hover:bg-accent-600">
                <FlaskConical size={13} /> Evaluate this adapter <ArrowRight size={13} />
              </Link>
              <span className="text-[11px] text-ink-500">
                Run the eval sets and promotion gate against it.
              </span>
            </div>
          ) : detail.run.status === "completed" && detail.run.smoke_test ? (
            <div className="text-[11px] text-ink-500">
              Smoke test passed. Launch a full run from{" "}
              <Link href="/train" className="font-semibold text-accent-600 underline underline-offset-2">
                Train
              </Link>{" "}to train for real.
            </div>
          ) : null}

          {/* Reproducibility: exact config + data fingerprint this run used. */}
          {picked ? <RunConfigPanel key={`cfg-${picked}`} adapterDir={picked} /> : null}
        </>
      ) : null}

      {/* Full log for the selected run — unless it's the active run, whose
          streaming log already shows in the Live section above. Collapsed by
          default: its own header is a one-line summary that expands on demand,
          so an empty log never fills a whole panel. */}
      {picked && !(live?.active && live.run?.adapter_dir === picked) ? (
        <TrainingLogPanel key={picked} adapterDir={picked} tail={1000} />
      ) : null}

      {picked ? (
        <div className="text-xs text-ink-500">
          Inspecting <code>{picked}</code>. Pick another from the list above.
        </div>
      ) : null}
    </div>
  );
}
