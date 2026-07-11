"use client";
import * as React from "react";
import useSWR from "swr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useShallow } from "zustand/react/shallow";
import { Check, MessageSquare, Pencil, Plus, Search, Trash2, X } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtRelative } from "@/lib/format";
import { Button } from "@/components/ui/Button";
import { useChatStore } from "@/lib/stores/chatStore";
import type { ThreadSummary } from "@/lib/types";
import { ModelPicker } from "./ModelPicker";

const MODEL_STORAGE_KEY = "puffin_copilot_default_model";

type Group = { label: string; threads: ThreadSummary[] };

function groupThreads(threads: ThreadSummary[]): Group[] {
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startYesterday = new Date(startOfDay.getTime() - 86_400_000);
  const startWeek = new Date(startOfDay.getTime() - 6 * 86_400_000);

  const groups: Group[] = [
    { label: "Today", threads: [] },
    { label: "Yesterday", threads: [] },
    { label: "Previous 7 days", threads: [] },
    { label: "Older", threads: [] },
  ];
  for (const t of threads) {
    const d = new Date(t.updated_at);
    if (Number.isNaN(d.getTime()) || d >= startOfDay) groups[0].threads.push(t);
    else if (d >= startYesterday) groups[1].threads.push(t);
    else if (d >= startWeek) groups[2].threads.push(t);
    else groups[3].threads.push(t);
  }
  return groups.filter((g) => g.threads.length > 0);
}

export function ThreadList({ activeId }: { activeId?: string | null }) {
  const router = useRouter();
  const { data, mutate } = useSWR("threads", () => api.listThreads(),
    { refreshInterval: 10_000 });
  const { data: modelsData } = useSWR("models", () => api.models());

  const [pickedModel, setPickedModel] = React.useState<string>("");
  const [query, setQuery] = React.useState("");
  const [renameId, setRenameId] = React.useState<string | null>(null);
  const [renameDraft, setRenameDraft] = React.useState("");
  const [deleteArmId, setDeleteArmId] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);

  // Thread ids with a live stream: pulses the row so a background reply
  // is visible from the list.
  const streamingIds = useChatStore(useShallow((s) =>
    Object.keys(s.threads).filter((id) => s.threads[id].isStreaming)));

  // Resolve the default model for NEW chats: the stored preference if it's
  // still usable, else the catalog default, else the first available model.
  // Prevents new threads from silently targeting a vendor with no key.
  React.useEffect(() => {
    if (!modelsData) return;
    const stored = typeof window !== "undefined"
      ? window.localStorage.getItem(MODEL_STORAGE_KEY)
      : null;
    const byId = new Map(modelsData.models.map((m) => [m.id, m]));
    const usable = (id: string | null | undefined) =>
      Boolean(id && byId.get(id)?.available);

    setPickedModel((current) => {
      if (usable(current)) return current;
      if (usable(stored)) return stored as string;
      if (usable(modelsData.default)) return modelsData.default;
      const firstAvailable = modelsData.models.find((m) => m.available);
      return firstAvailable?.id ?? stored ?? modelsData.default;
    });
  }, [modelsData]);

  const updateModel = (id: string) => {
    setPickedModel(id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(MODEL_STORAGE_KEY, id);
    }
  };

  const create = React.useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const { thread } = await api.createThread({
        title: "New conversation",
        ...(pickedModel ? { model: pickedModel } : {}),
      });
      await mutate();
      router.push(`/?t=${thread.id}`);
    } finally {
      setCreating(false);
    }
  }, [creating, pickedModel, mutate, router]);
  const createRef = React.useRef(create);
  createRef.current = create;

  // Ctrl+Shift+O: new chat from anywhere (matches the hint in the hero).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        void createRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Auto-disarm the delete confirmation after a beat.
  React.useEffect(() => {
    if (!deleteArmId) return;
    const t = window.setTimeout(() => setDeleteArmId(null), 3_500);
    return () => window.clearTimeout(t);
  }, [deleteArmId]);

  const remove = async (id: string) => {
    setDeleteArmId(null);
    await api.deleteThread(id);
    void mutate();
    if (id === activeId) router.push("/");
  };

  const commitRename = async () => {
    const id = renameId;
    const title = renameDraft.trim();
    setRenameId(null);
    if (!id || !title) return;
    await api.updateThread(id, { title });
    void mutate();
  };

  const modelLabel = React.useCallback((id: string) => {
    const m = modelsData?.models.find((x) => x.id === id);
    const label = m?.label ?? id.split(":")[0];
    return label.split(" (")[0];
  }, [modelsData]);

  const threads = data?.threads ?? [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? threads.filter((t) => t.title.toLowerCase().includes(q))
    : threads;
  const groups = groupThreads(filtered);

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-ink-200 bg-card">
      <div className="space-y-2 border-b border-ink-200 px-3 py-3">
        <ModelPicker value={pickedModel} onChange={updateModel} />
        <Button
          variant="primary"
          size="md"
          className="w-full"
          onClick={() => void create()}
          disabled={creating}
          title="New chat (Ctrl+Shift+O)"
        >
          <Plus size={14} /> New chat
        </Button>
        <div className="relative">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations"
            aria-label="Search conversations"
            className="h-8 w-full rounded-lg border border-ink-200 bg-ink-50 pl-8 pr-7
                       text-xs placeholder:text-ink-400 focus:border-accent
                       focus:bg-card focus:outline-none"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5
                         text-ink-400 hover:text-ink"
            >
              <X size={12} />
            </button>
          ) : null}
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2" aria-label="Conversations">
        {groups.map((g) => (
          <div key={g.label} className="mb-1">
            <div className="px-4 pb-1 pt-2 text-[10px] font-bold uppercase
                            tracking-wider text-ink-400">
              {g.label}
            </div>
            {g.threads.map((t) => {
              const isActive = activeId === t.id;
              const isRenaming = renameId === t.id;
              const isArmed = deleteArmId === t.id;
              const isStreamingThread = streamingIds.includes(t.id);
              return (
                <Link
                  key={t.id}
                  href={`/?t=${t.id}`}
                  className={cn(
                    "group mx-2 mb-0.5 flex items-start gap-2 rounded-lg px-2.5 py-2",
                    "text-sm transition-colors",
                    isActive
                      ? "bg-accent/10 text-ink"
                      : "text-ink-700 hover:bg-ink-100",
                  )}
                >
                  <MessageSquare
                    size={14}
                    className={cn(
                      "mt-0.5 shrink-0",
                      isActive ? "text-amber-600" : "text-ink-400",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    {isRenaming ? (
                      <input
                        autoFocus
                        value={renameDraft}
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
                        onBlur={() => void commitRename()}
                        onKeyDown={(e) => {
                          e.stopPropagation();
                          if (e.key === "Enter") { e.preventDefault(); void commitRename(); }
                          if (e.key === "Escape") { e.preventDefault(); setRenameId(null); }
                        }}
                        aria-label="Rename conversation"
                        className="w-full rounded border border-accent bg-card px-1.5
                                   py-0.5 text-xs font-semibold focus:outline-none"
                      />
                    ) : (
                      <div className="truncate text-[13px] font-semibold text-ink">
                        {t.title}
                      </div>
                    )}
                    <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-ink-400">
                      {isStreamingThread ? (
                        <span className="inline-flex items-center gap-1 font-bold text-amber-600">
                          <span className="h-1.5 w-1.5 animate-pulseDot rounded-full bg-amber-500" />
                          replying
                        </span>
                      ) : (
                        <span>{fmtRelative(t.updated_at)}</span>
                      )}
                      <span className="text-ink-300">·</span>
                      <span className="truncate">{modelLabel(t.model)}</span>
                    </div>
                  </div>

                  <div
                    className={cn(
                      "flex shrink-0 items-center gap-0.5 pt-0.5 transition-opacity",
                      isArmed || isRenaming
                        ? "opacity-100"
                        : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
                    )}
                  >
                    {isArmed ? (
                      <>
                        <button
                          onClick={(e) => {
                            e.preventDefault(); e.stopPropagation();
                            void remove(t.id);
                          }}
                          aria-label="Confirm delete"
                          title="Confirm delete"
                          className="rounded bg-red-600 p-1 text-white hover:bg-red-700"
                        >
                          <Check size={11} />
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault(); e.stopPropagation();
                            setDeleteArmId(null);
                          }}
                          aria-label="Cancel delete"
                          title="Cancel"
                          className="rounded border border-ink-200 bg-card p-1
                                     text-ink-500 hover:bg-ink-50"
                        >
                          <X size={11} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={(e) => {
                            e.preventDefault(); e.stopPropagation();
                            setRenameId(t.id);
                            setRenameDraft(t.title);
                          }}
                          aria-label="Rename conversation"
                          title="Rename"
                          className="rounded p-1 text-ink-400 hover:bg-card hover:text-ink"
                        >
                          <Pencil size={11} />
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault(); e.stopPropagation();
                            setDeleteArmId(t.id);
                          }}
                          aria-label="Delete conversation"
                          title="Delete"
                          className="rounded p-1 text-ink-400 hover:bg-card hover:text-red-600"
                        >
                          <Trash2 size={11} />
                        </button>
                      </>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        ))}

        {threads.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-ink-400">
            No conversations yet.
            <br />Click <b>New chat</b> to start.
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-ink-400">
            No conversations match “{query}”.
          </div>
        ) : null}
      </nav>
    </aside>
  );
}
