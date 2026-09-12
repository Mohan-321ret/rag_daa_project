"""
Prompt Builder  –  Phase 9 Module 7 (Step 4: Prompt Builder)
------------------------------------------------------------------
Assembles the final LLM prompt from Context Fusion's optimized chunks
(deduped → cross-encoder reranked → compressed). This is the pipeline's
Output: Optimized Context, formatted into a numbered, cited context block
and combined with the system/user prompt templates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert enterprise knowledge assistant. Answer the user's question based on the provided context excerpts below.

Rules:
- Do NOT output <think> tags, chain-of-thought, or internal reasoning blocks. Output ONLY the final answer directly.
- Synthesize a helpful, well-structured answer using any relevant facts present in the context excerpts (e.g. names, IDs, roles, organization names, dates, or document authorship).
- ALWAYS cite the source document ID (e.g. [DOC_8D012608]) whenever stating facts from the context.
- Do NOT hallucinate or introduce facts that are not present in the context.
- Only say "I don't have enough information in the provided documents to answer this." if the context contains absolutely no relevant facts or mentions related to the question.

Context:
{context}
"""

_USER_PROMPT_TEMPLATE = "Question: {question}\n\nAnswer:"


@dataclass
class BuiltPrompt:
    optimized_context: str
    system_prompt: str
    user_prompt: str
    full_prompt: str


def build_optimized_context(results: List[dict]) -> str:
    """
    Format the fused (deduped/reranked/compressed) chunks into a numbered,
    citable context block — the pipeline's "Optimized Context" output.
    """
    if not results:
        return "(No relevant context found.)"

    lines: List[str] = []
    for i, r in enumerate(results, start=1):
        doc_id = r.get("document_id") or r.get("metadata", {}).get("document_id", "unknown")
        chunk_idx = r.get("chunk_index", r.get("metadata", {}).get("chunk_index", "?"))
        score = r.get("score", 0.0)
        source = r.get("source", "?")
        text = (r.get("text") or "").strip()
        lines.append(
            f"[{i}] Source: {doc_id} | Chunk: {chunk_idx} | Retriever: {source} | Score: {score:.4f}\n"
            f"{text}"
        )
    return "\n\n---\n\n".join(lines)


def build_prompt(query: str, results: List[dict]) -> BuiltPrompt:
    """Build the optimized context block and the full system+user prompt."""
    optimized_context = build_optimized_context(results)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(context=optimized_context)
    user_prompt = _USER_PROMPT_TEMPLATE.format(question=query)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    return BuiltPrompt(
        optimized_context=optimized_context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        full_prompt=full_prompt,
    )
