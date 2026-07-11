"use client";
/**
 * Ask-AI-anywhere: hand a prompt from any page to the chat.
 *
 * Pages queue a prompt (sessionStorage survives the route change), navigate
 * to "/", and ChatThread consumes + auto-sends it into the active thread.
 * The AI has tools for every pipeline stage, so this is how any button in
 * the app can say "have the AI do it".
 */
const KEY = "puffin_pending_ai_prompt";

export function queueAIPrompt(prompt: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(KEY, prompt);
}

export function consumeAIPrompt(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.sessionStorage.getItem(KEY);
  if (v) window.sessionStorage.removeItem(KEY);
  return v;
}

/** Page-aware prompt suggestions for the global command bar. */
export function pageSuggestions(pathname: string): string[] {
  if (pathname.startsWith("/data")) {
    return [
      "Audit my raw data and tell me if it's ready to train",
      "Run the data pipeline and build train/eval/test splits",
      "Import a dataset from Hugging Face for me",
    ];
  }
  if (pathname.startsWith("/train")) {
    return [
      "Recommend the best training recipe for my data and smoke-test it",
      "Run a smoke train and watch it live",
      "Launch a QLoRA run with rank 32 on my dataset",
    ];
  }
  if (pathname.startsWith("/runs")) {
    return [
      "Compare my recent training runs and pick the best",
      "Why did my last run's loss plateau?",
    ];
  }
  if (pathname.startsWith("/evaluate")) {
    return [
      "Run all evals and apply the promotion gate",
      "Walk me through my latest eval metrics and what to fix",
    ];
  }
  if (pathname.startsWith("/deploy")) {
    return [
      "Push the adapter to the registry",
      "Promote the latest model version to staging",
    ];
  }
  if (pathname.startsWith("/monitor")) {
    return [
      "Diagnose drift and quality on production traffic",
      "Show the last 25 requests and flag anything odd",
    ];
  }
  if (pathname.startsWith("/playground")) {
    return [
      "Chat with my deployed model and sanity-check its answers",
    ];
  }
  return [
    "What's the state of this project? What should I do next?",
    "Take me from raw data to a deployed model, step by step",
  ];
}
