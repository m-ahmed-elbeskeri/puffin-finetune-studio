"use client";
import * as React from "react";
import { cn } from "@/lib/cn";

interface Tab {
  key: string;
  label: React.ReactNode;
  badge?: React.ReactNode;
}

export function Tabs({
  tabs, value, onChange,
}: {
  tabs: Tab[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="border-b border-ink-200">
      <div className="flex gap-2" role="tablist">
        {tabs.map((t) => {
          const active = t.key === value;
          return (
            <button
              key={t.key}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.key)}
              className={cn(
                "px-3 py-2 text-sm font-semibold border-b-2 -mb-px",
                "transition-colors flex items-center gap-2",
                active
                  ? "border-accent text-ink"
                  : "border-transparent text-ink-500 hover:text-ink",
              )}
            >
              {t.label}
              {t.badge}
            </button>
          );
        })}
      </div>
    </div>
  );
}
