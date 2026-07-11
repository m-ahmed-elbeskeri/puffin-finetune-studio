"""RAG context formatting — must be identical between RAG ingestion and serving."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievedDocument:
    """One retrieved chunk shown to the model."""

    id: str
    text: str
    source: str = ""
    score: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)


_RAG_HEADER = (
    "Use the following retrieved context to answer the user. "
    "If the context does not contain the answer, say so. "
    "Cite sources by their [id]."
)


def format_rag_context(documents: Sequence[RetrievedDocument]) -> str:
    """Render retrieved docs into a single system-message string.

    Format is stable and machine-parseable so eval harnesses can verify
    citation correctness.
    """
    if not documents:
        return _RAG_HEADER + "\n\n[No documents retrieved.]"

    lines = [_RAG_HEADER, ""]
    for doc in documents:
        header = f"[{doc.id}]"
        if doc.source:
            header += f" source={doc.source}"
        if doc.score:
            header += f" score={doc.score:.3f}"
        lines.append(header)
        lines.append(doc.text.strip())
        lines.append("")
    return "\n".join(lines).rstrip()
