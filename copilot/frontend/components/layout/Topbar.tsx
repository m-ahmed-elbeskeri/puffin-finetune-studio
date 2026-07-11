"use client";
import * as React from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { AskAIBar } from "@/components/ai/AskAI";
import { ProjectPicker } from "./ProjectPicker";

const fetcher = () => api.state();

export function Topbar() {
  const { data } = useSWR("state", fetcher, { refreshInterval: 10_000 });
  const status = data?.status;
  const live = data?.training;

  return (
    <header className="h-12 px-4 flex items-center justify-between border-b border-ink-200 bg-card/80 backdrop-blur sticky top-0 z-20">
      <div className="flex items-center gap-3 text-sm text-ink-500">
        <ProjectPicker />
        {status ? (
          <>
            <span className="text-ink-300">·</span>
            <span className="hidden md:inline">
              {status.steps.filter(s => s.status === "done").length}
              {" / "}{status.steps.length} steps done
            </span>
          </>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <AskAIBar />
        {live?.active ? (
          <Badge tone="ok">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulseDot" />
            Training running
          </Badge>
        ) : null}
        {status?.hardware.gpu.available ? (
          <Badge tone="muted">{status.hardware.gpu.name?.split(" ").slice(-2).join(" ")}</Badge>
        ) : (
          <Badge tone="muted">CPU only</Badge>
        )}
      </div>
    </header>
  );
}
