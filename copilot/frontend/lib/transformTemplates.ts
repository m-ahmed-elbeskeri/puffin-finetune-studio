"use client";
/**
 * Prebuilt, editable transform-script templates.
 *
 * Each is a complete, standard-library-only Python script following the
 * transform contract (`--input in.jsonl --output out.jsonl`). They are
 * starting points: the user picks one, tweaks it to their data in the
 * editor, saves it to data/transforms/, and runs it. Redaction and dedupe
 * live here (rather than baked into the pipeline) so they're fully editable.
 */

export type TemplateCategory = "clean" | "filter" | "redact" | "dedupe" | "map";

export interface TransformTemplate {
  id: string;
  label: string;
  suggestedName: string;
  category: TemplateCategory;
  description: string;
  code: string;
}

export const CATEGORY_META: Record<TemplateCategory, {
  label: string; blurb: string;
}> = {
  redact: { label: "Redact", blurb: "Take private info out of the text" },
  dedupe: { label: "Dedupe", blurb: "Remove repeated records so they don't over-count" },
  filter: { label: "Filter", blurb: "Keep only the records worth training on" },
  clean: { label: "Clean", blurb: "Tidy up messy or inconsistent text" },
  map: { label: "Reshape", blurb: "Convert records into the chat format training expects" },
};

const HEADER = `"""%DOC%"""
import argparse
import json
import re
import sys
`;

function script(doc: string, body: string, summary: string): string {
  return `${HEADER.replace("%DOC%", doc)}

def transform(rec: dict) -> dict | None:
    """Return the modified record, or None to drop it."""
${body}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    kept = dropped = bad = 0
    with open(args.input, "r", encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            out = transform(rec)
            if out is None:
                dropped += 1
                continue
            fout.write(json.dumps(out, ensure_ascii=False) + "\\n")
            kept += 1
    print(${summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
`;
}

/** Iterate the text content of a record across the common schemas. */
const ITER_HELPER = `
def _each_text(rec):
    """Yield (setter, text) for every editable text field in a record."""
    msgs = rec.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                yield (lambda v, _m=m: _m.__setitem__("content", v)), m["content"]
    for key in ("prompt", "completion", "response", "chosen", "rejected"):
        if isinstance(rec.get(key), str):
            yield (lambda v, _k=key: rec.__setitem__(_k, v)), rec[key]
`;

export const TRANSFORM_TEMPLATES: TransformTemplate[] = [
  {
    id: "redact_pii",
    label: "Redact PII",
    suggestedName: "redact_pii.py",
    category: "redact",
    description: "Replaces emails, phone numbers, SSNs, and card-shaped numbers with tags like [EMAIL] so private data never reaches the model. Add your own patterns or names to scrub in the DENY_TERMS list.",
    code: `"""Redact PII (emails, phones, SSNs, cards) from all message content."""
import argparse
import json
import re

# Edit / extend these to match your data. Each (pattern, replacement).
PATTERNS = [
    (re.compile(r"[\\w.+-]+@[\\w-]+\\.[\\w.-]+"), "[EMAIL]"),
    (re.compile(r"\\b\\d{3}-\\d{2}-\\d{4}\\b"), "[SSN]"),
    (re.compile(r"\\b(?:\\+?\\d{1,3}[-.\\s]?)?\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b"), "[PHONE]"),
    (re.compile(r"\\b(?:\\d[ -]?){13,16}\\b"), "[CARD]"),
]

# Extra literal terms to scrub (names, internal codenames, etc.).
DENY_TERMS: list[str] = []


def scrub(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    for term in DENY_TERMS:
        if term:
            text = re.sub(re.escape(term), "[REDACTED]", text, flags=re.I)
    return text
${ITER_HELPER}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    kept = hits = bad = 0
    with open(args.input, "r", encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            for setter, text in _each_text(rec):
                new = scrub(text)
                if new != text:
                    hits += 1
                    setter(new)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\\n")
            kept += 1
    print(f"kept={kept} fields_redacted={hits} bad_json={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
`,
  },
  {
    id: "dedupe",
    label: "Deduplicate",
    suggestedName: "dedupe.py",
    category: "dedupe",
    description: "Removes records that repeat text you have already seen, ignoring case and spacing. Duplicates make the model over-weight those examples, so keeping just the first copy gives cleaner training. Keeps the first occurrence of each.",
    code: `"""Drop duplicate records by normalized-text hash (keeps first seen)."""
import argparse
import hashlib
import json
import re


def signature(rec: dict) -> str:
    """A stable fingerprint of the record's text, ignoring case + whitespace."""
    parts = []
    msgs = rec.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict):
                parts.append(f"{m.get('role')}:{m.get('content')}")
    else:
        for k in ("prompt", "completion", "response", "chosen", "rejected"):
            if rec.get(k) is not None:
                parts.append(f"{k}:{rec[k]}")
    blob = "\\u0001".join(parts)
    blob = re.sub(r"\\s+", " ", blob).strip().lower()
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    seen: set[str] = set()
    kept = dropped = bad = 0
    with open(args.input, "r", encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            sig = signature(rec)
            if sig in seen:
                dropped += 1
                continue
            seen.add(sig)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\\n")
            kept += 1
    print(f"kept={kept} duplicates_dropped={dropped} bad_json={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
`,
  },
  {
    id: "drop_short",
    label: "Drop short conversations",
    suggestedName: "drop_short.py",
    category: "filter",
    description: "Removes conversations that are too short to teach anything: fewer than MIN_TURNS messages, or less than MIN_CHARS of text. These are usually broken exports or trivial exchanges. Edit the two thresholds to fit your data.",
    code: script(
      "Drop conversations with too few turns or too little content.",
      `    MIN_TURNS = 2
    MIN_CHARS = 20
    msgs = rec.get("messages")
    if isinstance(msgs, list):
        if len(msgs) < MIN_TURNS:
            return None
        total = sum(len(str(m.get("content", ""))) for m in msgs
                    if isinstance(m, dict))
    else:
        total = len(str(rec.get("prompt", ""))) + len(str(rec.get("response", rec.get("completion", ""))))
    if total < MIN_CHARS:
        return None
    return rec`,
      'f"kept={kept} dropped={dropped} bad_json={bad}"'),
  },
  {
    id: "filter_length",
    label: "Filter by length",
    suggestedName: "filter_length.py",
    category: "filter",
    description: "Keeps records whose total length sits between MIN_CHARS and MAX_CHARS. Very long examples can blow past the model's context window and very short ones add noise, so trimming both tails helps. Set the window to match your model's max sequence length.",
    code: script(
      "Keep records whose total content length is within a window.",
      `    MIN_CHARS = 20
    MAX_CHARS = 8000
    msgs = rec.get("messages")
    if isinstance(msgs, list):
        total = sum(len(str(m.get("content", ""))) for m in msgs
                    if isinstance(m, dict))
    else:
        total = sum(len(str(rec.get(k, ""))) for k in
                    ("prompt", "completion", "response"))
    if total < MIN_CHARS or total > MAX_CHARS:
        return None
    return rec`,
      'f"kept={kept} dropped={dropped} bad_json={bad}"'),
  },
  {
    id: "strip_html",
    label: "Strip HTML & tidy whitespace",
    suggestedName: "strip_html.py",
    category: "clean",
    description: "Strips HTML and XML tags and squeezes repeated spaces into one. Web-scraped data is full of markup the model should never learn to produce, so this leaves clean plain text behind.",
    code: `"""Strip HTML tags and collapse whitespace in all message content."""
import argparse
import json
import re

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\\s+")


def clean(text: str) -> str:
    return WS.sub(" ", TAG.sub(" ", text)).strip()
${ITER_HELPER}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    kept = changed = bad = 0
    with open(args.input, "r", encoding="utf-8") as fin, \\
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            for setter, text in _each_text(rec):
                new = clean(text)
                if new != text:
                    changed += 1
                    setter(new)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\\n")
            kept += 1
    print(f"kept={kept} fields_cleaned={changed} bad_json={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
`,
  },
  {
    id: "map_prompt_completion",
    label: "Map prompt/completion → messages",
    suggestedName: "map_to_messages.py",
    category: "map",
    description: "Turns flat {prompt, completion} or {instruction, response} rows into the {messages: [...]} chat format that SFT training reads. Records that have neither a prompt nor a reply are dropped. Use this when your data came from a non-chat source.",
    code: script(
      "Convert prompt/completion records into chat messages schema.",
      `    if "messages" in rec:
        return rec  # already in chat schema
    prompt = rec.get("prompt") or rec.get("instruction") or rec.get("question")
    reply = (rec.get("completion") or rec.get("response")
             or rec.get("output") or rec.get("answer"))
    if not prompt or not reply:
        return None  # nothing to map, so drop the record
    messages = []
    system = rec.get("system") or rec.get("system_prompt")
    if system:
        messages.append({"role": "system", "content": str(system)})
    messages.append({"role": "user", "content": str(prompt)})
    messages.append({"role": "assistant", "content": str(reply)})
    out = {"messages": messages}
    for k in ("source", "license", "id"):
        if k in rec:
            out[k] = rec[k]
    return out`,
      'f"kept={kept} unmappable_dropped={dropped} bad_json={bad}"'),
  },
  {
    id: "normalize_roles",
    label: "Normalize message roles",
    suggestedName: "normalize_roles.py",
    category: "map",
    description: "Renames off-standard speaker labels (human, gpt, bot, ai) to the user, assistant, and system roles the chat template understands. Datasets from ShareGPT and similar sources often need this before they will train.",
    code: script(
      "Normalize message roles to system/user/assistant.",
      `    ROLE_MAP = {
        "human": "user", "user": "user", "prompter": "user",
        "gpt": "assistant", "assistant": "assistant", "bot": "assistant",
        "ai": "assistant", "system": "system",
    }
    msgs = rec.get("messages")
    if not isinstance(msgs, list):
        return rec
    for m in msgs:
        if isinstance(m, dict) and "role" in m:
            m["role"] = ROLE_MAP.get(str(m["role"]).lower(), str(m["role"]))
    return rec`,
      'f"kept={kept} dropped={dropped} bad_json={bad}"'),
  },
  {
    id: "add_system",
    label: "Add a system prompt",
    suggestedName: "add_system.py",
    category: "clean",
    description: "Adds the same system message to the front of every conversation that does not already have one. This is how you give the model a consistent persona or set of rules. Edit SYSTEM_PROMPT to whatever instruction you want baked in.",
    code: script(
      "Ensure every conversation starts with a fixed system prompt.",
      `    SYSTEM_PROMPT = "You are a helpful assistant."
    msgs = rec.get("messages")
    if not isinstance(msgs, list):
        return rec
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
        return rec  # already has one
    rec["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}, *msgs]
    return rec`,
      'f"kept={kept} dropped={dropped} bad_json={bad}"'),
  },
];

export function templatesByCategory(): Array<{
  category: TemplateCategory; items: TransformTemplate[];
}> {
  const order: TemplateCategory[] = ["redact", "dedupe", "filter", "clean", "map"];
  return order
    .map((category) => ({
      category,
      items: TRANSFORM_TEMPLATES.filter((t) => t.category === category),
    }))
    .filter((g) => g.items.length > 0);
}
