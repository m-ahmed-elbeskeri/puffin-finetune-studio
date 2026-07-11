"""Interactive tools — pause the agent loop to surface a UI affordance.

`ask_user_question` is the headline one. Claude calls it when it needs a
clarifying choice from the user; the result payload is rendered as a
button card in the frontend; the user's pick comes back as the next chat
message naturally.

We don't suspend execution server-side. The contract is simpler:
- The tool returns `{kind: "ask_user_question", awaiting_user_input: true}`.
- The system prompt instructs Claude to STOP after calling this tool
  (don't speculate the answer or chain another tool).
- The frontend renders the card with one button per option. Clicking a
  button sends a freshly-composed user message: "Re: <header> — <label>".
- Conversation continues normally.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, tool


class _Option(BaseModel):
    label: str = Field(description="Short display text on the button (1–5 words).")
    description: str = Field(
        default="",
        description="Optional explanation shown under the label.",
    )


class AskUserQuestionArgs(BaseModel):
    question: str = Field(
        description="The complete question. Should end with '?'.",
    )
    header: str = Field(
        description=(
            "Very short label shown as a chip on the card (max 12 chars). "
            "Examples: 'Auth method', 'Library', 'Approach'."
        ),
        max_length=24,
    )
    options: list[_Option] = Field(
        description=(
            "2–4 distinct choices. Don't include an 'Other' option — the UI "
            "always provides one automatically."
        ),
        min_length=2,
        max_length=6,
    )
    multi_select: bool = Field(
        default=False,
        description="True if multiple options may be selected together.",
    )


@tool(
    "ask_user_question",
    description=(
        "Pause and ask the user a clarifying multiple-choice question. Use "
        "whenever a decision affects what tool to call next or risks "
        "wasting compute (e.g. 'smoke or full train?', 'which dataset?', "
        "'which adapter to promote?'). After calling this tool, STOP — "
        "do not chain more tool calls or speculate the answer. The user's "
        "reply will arrive as the next message and you can continue from "
        "there.\n\n"
        "Examples of good headers: 'Method', 'Smoke or full', 'Adapter', "
        "'Threshold'.\n\n"
        "Do NOT use this tool for yes/no confirmations of harmless "
        "read-only actions — just do the read. Use it when there's a real "
        "branch in the plan."
    ),
    args_model=AskUserQuestionArgs,
)
async def ask_user_question(
    args: AskUserQuestionArgs, ctx: ToolContext,  # noqa: ARG001
) -> dict[str, Any]:
    return {
        "kind": "ask_user_question",
        "question": args.question,
        "header": args.header,
        "options": [o.model_dump() for o in args.options],
        "multi_select": args.multi_select,
        "awaiting_user_input": True,
    }
