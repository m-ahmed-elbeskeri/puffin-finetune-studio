"use client";
import * as React from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, Save } from "@/components/ui/icons";
import { useCodeActions } from "@/lib/codeActions";

/**
 * Fenced code block with a header (language label + copy button).
 * Memoized: during streaming, re-highlighting every block on every text
 * delta is the single biggest render cost in the thread.
 */
export const CodeBlock = React.memo(function CodeBlock({
  language,
  code,
}: {
  language: string;
  code: string;
}) {
  const [copied, setCopied] = React.useState(false);
  const actions = useCodeActions();
  const showAction = Boolean(
    actions && actions.languages.includes((language || "").toLowerCase()));

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_400);
    } catch {
      /* clipboard unavailable (http, permissions): silently ignore */
    }
  };

  return (
    <div className="group/code my-2 overflow-hidden rounded-xl border border-ink-800/60">
      <div className="flex items-center justify-between bg-[#1e2430] px-3 py-1.5">
        <span className="text-[10px] font-bold uppercase tracking-wider text-ink-400">
          {language || "code"}
        </span>
        <span className="flex items-center gap-1">
          {showAction && actions ? (
            <button
              type="button"
              onClick={() => actions.onAction(code)}
              className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/15
                         px-2 py-1 text-[11px] font-semibold text-amber-300
                         transition-colors hover:bg-amber-500/25"
            >
              <Save size={12} />
              {actions.label}
            </button>
          ) : null}
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px]
                       text-ink-400 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="Copy code"
          >
            {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            {copied ? "Copied" : "Copy"}
          </button>
        </span>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={language || "text"}
        PreTag="div"
        customStyle={{
          fontSize: "0.82em",
          borderRadius: 0,
          padding: "14px 16px",
          margin: 0,
          background: "#0f172a",
        }}
        codeTagProps={{
          style: { fontFamily: "var(--font-mono, ui-monospace, monospace)" },
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
});
