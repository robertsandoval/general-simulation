"""Stub solver — deterministic, explainable placeholder for Stage-2.

Proves the Solver interface and lets the full reasoning pipeline run
end-to-end without any domain-specific OR-Tools implementation.

What it computes (all from the affected subgraph + live state alone):
  1. ``affected_count``    — len(subgraph.affected_entity_ids)
  2. ``max_chain_length``  — length of the longest path through the
                             dependency sub-DAG  (DFS with memoisation)
  3. ``impact_score``      — weighted combination of the above (0.0–1.0)
  4. ``response_options``  — tiered options calibrated to the impact level

Nothing here is domain-specific.  Replace this with a real OR-Tools or
discrete-event solver by implementing the ``Solver`` Protocol in a new
``src/solver/<domain>.py`` file and injecting it instead.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.solver import (
    AffectedSubgraph,
    LiveState,
    ResponseOption,
    Solver,
    SolverResult,
)

logger = logging.getLogger(__name__)

# Weights used to combine sub-metrics into a single impact score.
_WEIGHT_COUNT = 0.15
_WEIGHT_CHAIN = 0.25
_MAX_SCORE = 1.0

# Impact thresholds for choosing the response tier.
_THRESHOLD_LOW = 0.25
_THRESHOLD_MED = 0.55


class StubSolver:
    """Deterministic stub that satisfies the Solver Protocol.

    Output is fully determined by the *structure* of the affected subgraph
    (entity count + dependency topology).  No randomness, no external calls.

    This intentional simplicity makes it easy to assert exact values in
    tests and easy to reason about in Stage-3 prompts.
    """

    # ── Solver Protocol ───────────────────────────────────────────────────────

    def solve(
        self,
        subgraph: AffectedSubgraph,
        live_state: LiveState,
    ) -> SolverResult:
        affected_count = len(subgraph.affected_entity_ids)
        chain_len = _longest_chain(
            subgraph.dependency_edges,
            set(subgraph.affected_entity_ids),
        )
        impact = _impact_score(affected_count, chain_len)
        options = _response_options(impact)
        explanation = _explanation(subgraph, live_state, affected_count, chain_len, impact)

        logger.debug(
            "StubSolver: event=%s count=%d chain=%d score=%.3f",
            subgraph.event_id,
            affected_count,
            chain_len,
            impact,
        )

        return SolverResult(
            event_id=subgraph.event_id,
            affected_count=affected_count,
            max_chain_length=chain_len,
            impact_score=round(impact, 4),
            response_options=options,
            explanation=explanation,
            metadata={
                "solver": "stub",
                "scenario_id": subgraph.scenario_id,
                "edge_count": len(subgraph.dependency_edges),
            },
        )


# ---------------------------------------------------------------------------
# Pure helpers (testable independently)
# ---------------------------------------------------------------------------


def _longest_chain(
    edges: list[tuple[str, str, str]],
    nodes: set[str],
) -> int:
    """Return the number of *hops* on the longest path through the DAG.

    An isolated node has chain length 0.  A single edge A→B gives length 1.
    Cycles (which should not occur in a dependency graph) are broken by the
    memoisation guard — each node is visited at most once.
    """
    if not edges or not nodes:
        return 0

    # Build forward adjacency list restricted to the affected subgraph nodes.
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for from_id, to_id, _ in edges:
        if from_id in adj and to_id in adj:
            adj[from_id].append(to_id)

    memo: dict[str, int] = {}

    def _dfs(node: str, visiting: frozenset[str]) -> int:
        if node in memo:
            return memo[node]
        successors = [s for s in adj.get(node, []) if s not in visiting]
        if not successors:
            memo[node] = 0
            return 0
        depth = 1 + max(_dfs(s, visiting | {node}) for s in successors)
        memo[node] = depth
        return depth

    return max(_dfs(n, frozenset()) for n in nodes)


def _impact_score(affected_count: int, chain_length: int) -> float:
    """Dimensionless severity score in [0.0, 1.0]."""
    raw = affected_count * _WEIGHT_COUNT + chain_length * _WEIGHT_CHAIN
    return min(_MAX_SCORE, raw)


def _response_options(impact: float) -> list[ResponseOption]:
    """Return a tier of ranked response options based on impact severity."""
    if impact < _THRESHOLD_LOW:
        return [
            ResponseOption(
                rank=1,
                label="monitor_and_log",
                description=(
                    "Impact is low.  Continue normal operations; "
                    "log the event for post-hoc analysis."
                ),
                estimated_impact_reduction=0.0,
            ),
        ]
    if impact < _THRESHOLD_MED:
        return [
            ResponseOption(
                rank=1,
                label="trigger_downstream_alerts",
                description=(
                    "Notify downstream entities of the perturbation so they "
                    "can adjust their own operations preemptively."
                ),
                estimated_impact_reduction=0.35,
            ),
            ResponseOption(
                rank=2,
                label="reroute_dependencies",
                description=(
                    "Temporarily redirect flows through alternative dependency "
                    "paths to bypass affected entities."
                ),
                estimated_impact_reduction=0.60,
            ),
        ]
    # High impact
    return [
        ResponseOption(
            rank=1,
            label="emergency_response",
            description=(
                "Activate emergency protocols across all affected entities. "
                "Escalate to human decision-makers immediately."
            ),
            estimated_impact_reduction=0.80,
        ),
        ResponseOption(
            rank=2,
            label="isolate_affected_entities",
            description=(
                "Isolate affected entities from the wider dependency graph "
                "to prevent cascade propagation."
            ),
            estimated_impact_reduction=0.65,
        ),
        ResponseOption(
            rank=3,
            label="notify_stakeholders",
            description=(
                "Broadcast impact summary to all registered stakeholders "
                "for coordinated response planning."
            ),
            estimated_impact_reduction=0.20,
        ),
    ]


def _explanation(
    subgraph: AffectedSubgraph,
    live_state: LiveState,
    affected_count: int,
    chain_len: int,
    impact: float,
) -> str:
    """Build a plain-English explanation for Stage-3 prompt context."""
    status_counts: dict[str, int] = {}
    for eid in subgraph.affected_entity_ids:
        state = live_state.get(eid)
        s = state.status if state else "unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    status_summary = ", ".join(
        f"{count} '{status}'" for status, count in sorted(status_counts.items())
    )
    chain_note = (
        f"The longest dependency chain through the affected subgraph is "
        f"{chain_len} hop(s)."
        if chain_len > 0
        else "There are no dependency edges within the affected subgraph."
    )

    return (
        f"StubSolver analysis for event '{subgraph.event_id}' "
        f"(scenario '{subgraph.scenario_id}'): "
        f"{affected_count} entit{'y' if affected_count == 1 else 'ies'} affected "
        f"with statuses — {status_summary or 'none recorded'}. "
        f"{chain_note} "
        f"Computed impact score: {impact:.3f} "
        f"(weights: count×{_WEIGHT_COUNT}, chain×{_WEIGHT_CHAIN})."
    )
