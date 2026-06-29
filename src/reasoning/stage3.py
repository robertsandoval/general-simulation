"""Stage 3 — Synthesis: vector retrieval + LLM generation via Llama Stack.

The LLM receives:
  - The user's question
  - Retrieved event descriptions (vector_search against the scenario DB)
  - Stage-1 structural facts (entity count, dependency chain)
  - Stage-2 solver numbers (impact score, response options)

The LLM EXPLAINS the impact using these numbers.
It must NOT invent figures beyond what Stages 1 & 2 produced.

All LLM and vector calls go through the LLMClientBase — never directly
to individual backends.
"""
from __future__ import annotations

import logging

from src.core.solver import AffectedSubgraph, SolverResult
from src.llm.base import LLMClientBase
from src.llm.types import Message

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a simulation impact analyst.
Answer the user's question using ONLY the data provided in the analysis sections below.
Do NOT invent impact numbers, probabilities, or entity counts beyond what is stated.
Cite the Stage-1 and Stage-2 figures directly in your response.
Your role is to explain — not to compute additional estimates.\
"""


async def run_stage3(
    question: str,
    subgraph: AffectedSubgraph,
    solver_result: SolverResult,
    llm_client: LLMClientBase,
) -> str:
    """Retrieve vector context and generate a grounded answer.

    Returns the synthesised answer string (or a fallback if generation fails).
    """
    vector_db_id = f"sim_events_{subgraph.scenario_id}"

    # Retrieve relevant event descriptions from the scenario vector DB.
    chunks = await llm_client.vector_search(question, vector_db_id, top_k=3)
    vector_context = (
        "\n\n".join(c.content for c in chunks)
        if chunks
        else "No event context found in the vector store for this scenario."
    )

    user_message = _build_user_message(question, subgraph, solver_result, vector_context)

    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=user_message),
    ]

    result = await llm_client.generate(messages)

    answer = result.content or ""
    if not answer:
        logger.warning(
            "Stage 3: generate() returned no content (stop_reason=%s)",
            result.stop_reason,
        )
        answer = (
            f"[Synthesis unavailable] "
            f"Scenario '{subgraph.scenario_id}' affects {solver_result.affected_count} "
            f"entit{'y' if solver_result.affected_count == 1 else 'ies'} "
            f"with impact score {solver_result.impact_score:.3f}."
        )

    logger.info(
        "Stage 3 complete: scenario=%s answer_len=%d",
        subgraph.scenario_id,
        len(answer),
    )
    return answer


def _build_user_message(
    question: str,
    subgraph: AffectedSubgraph,
    solver_result: SolverResult,
    vector_context: str,
) -> str:
    entity_list = (
        ", ".join(subgraph.affected_entity_ids[:10])
        + (" …" if len(subgraph.affected_entity_ids) > 10 else "")
        if subgraph.affected_entity_ids
        else "(none)"
    )

    options_text = "\n".join(
        f"  {opt.rank}. [{opt.label}] {opt.description} "
        f"(estimated impact reduction: {opt.estimated_impact_reduction:.0%})"
        for opt in solver_result.response_options
    )

    return f"""\
QUESTION: {question}

─── EVENT CONTEXT (vector search — semantic retrieval) ───────────────────────
{vector_context}

─── STAGE-1: STRUCTURAL ANALYSIS (deterministic — no LLM) ───────────────────
Scenario:                {subgraph.scenario_id}
Affected entities ({solver_result.affected_count}): {entity_list}
Longest dependency chain: {solver_result.max_chain_length} hop(s)

─── STAGE-2: QUANTITATIVE ANALYSIS (solver output) ──────────────────────────
Impact score:       {solver_result.impact_score:.4f}
Affected count:     {solver_result.affected_count}

Response options (ranked):
{options_text if options_text else "  (none)"}

Solver explanation:
{solver_result.explanation}

─────────────────────────────────────────────────────────────────────────────
Using only the data above, answer the question concisely and cite the numbers.\
"""
