"""Tests for the solver interface and StubSolver.

All tests are synchronous / async-free (the solver itself is sync).
The tool wrapper is tested with a canned subgraph — no DB or LLM required.

Build-plan "done when" check:
  "The reasoning pipeline can call solve() and get a structured SolverResult
  from the stub."
"""
from __future__ import annotations

import pytest

from src.core.solver import (
    AffectedSubgraph,
    EntityState,
    LiveState,
    ResponseOption,
    Solver,
    SolverResult,
)
from src.solver import StubSolver, call_solver_tool
from src.solver.stub import (
    _impact_score,
    _longest_chain,
    _response_options,
)
from src.solver.tool import SOLVER_TOOL_SCHEMA


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _subgraph(
    event_id: str = "evt-1",
    scenario_id: str = "s1",
    entities: list[str] | None = None,
    edges: list[tuple[str, str, str]] | None = None,
) -> AffectedSubgraph:
    return AffectedSubgraph(
        event_id=event_id,
        scenario_id=scenario_id,
        affected_entity_ids=entities or ["A", "B", "C"],
        dependency_edges=edges or [
            ("A", "B", "DEPENDS_ON"),
            ("B", "C", "DEPENDS_ON"),
        ],
    )


def _live_state(entity_ids: list[str]) -> LiveState:
    return {
        eid: EntityState(
            entity_id=eid,
            status="reviewed" if i % 2 == 0 else "automatic",
            attributes={"index": i},
        )
        for i, eid in enumerate(entity_ids)
    }


# ── Solver Protocol conformance ───────────────────────────────────────────────


def test_stub_solver_satisfies_protocol():
    assert isinstance(StubSolver(), Solver)


# ── _longest_chain (pure helper) ──────────────────────────────────────────────


def test_longest_chain_linear():
    edges = [("A", "B", "D"), ("B", "C", "D"), ("C", "D_node", "D")]
    assert _longest_chain(edges, {"A", "B", "C", "D_node"}) == 3


def test_longest_chain_branching():
    # A → B → D (len 2)
    # A → C     (len 1)
    # Longest from A = 2
    edges = [("A", "B", "D"), ("A", "C", "D"), ("B", "D_node", "D")]
    assert _longest_chain(edges, {"A", "B", "C", "D_node"}) == 2


def test_longest_chain_no_edges():
    assert _longest_chain([], {"A", "B"}) == 0


def test_longest_chain_single_node():
    assert _longest_chain([], {"A"}) == 0


def test_longest_chain_disconnected():
    # Two separate chains; max is 2
    edges = [("A", "B", "D"), ("C", "D_node", "D"), ("D_node", "E", "D")]
    assert _longest_chain(edges, {"A", "B", "C", "D_node", "E"}) == 2


def test_longest_chain_ignores_edges_outside_subgraph():
    # "X" is not in the node set → edge A→X should not extend chain
    edges = [("A", "B", "D"), ("B", "X", "D")]
    assert _longest_chain(edges, {"A", "B"}) == 1


# ── _impact_score (pure helper) ───────────────────────────────────────────────


def test_impact_score_zero_zero():
    assert _impact_score(0, 0) == 0.0


def test_impact_score_capped_at_one():
    assert _impact_score(100, 100) == 1.0


def test_impact_score_increases_with_count():
    assert _impact_score(5, 0) > _impact_score(2, 0)


def test_impact_score_increases_with_chain():
    assert _impact_score(0, 4) > _impact_score(0, 2)


# ── _response_options tiers ───────────────────────────────────────────────────


def test_response_options_low_impact_single_option():
    opts = _response_options(0.10)
    assert len(opts) == 1
    assert opts[0].label == "monitor_and_log"


def test_response_options_medium_impact_two_options():
    opts = _response_options(0.40)
    assert len(opts) == 2
    labels = {o.label for o in opts}
    assert "trigger_downstream_alerts" in labels
    assert "reroute_dependencies" in labels


def test_response_options_high_impact_three_options():
    opts = _response_options(0.75)
    assert len(opts) == 3
    assert opts[0].label == "emergency_response"


def test_response_options_ranked_ascending():
    for score in [0.10, 0.40, 0.75]:
        opts = _response_options(score)
        ranks = [o.rank for o in opts]
        assert ranks == sorted(ranks)


def test_response_options_impact_reduction_in_range():
    for score in [0.10, 0.40, 0.75]:
        for opt in _response_options(score):
            assert 0.0 <= opt.estimated_impact_reduction <= 1.0


# ── StubSolver.solve ──────────────────────────────────────────────────────────


def test_solve_returns_solver_result():
    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert isinstance(result, SolverResult)


def test_solve_affected_count_matches_entities():
    sg = _subgraph(entities=["X", "Y", "Z", "W"])
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert result.affected_count == 4


def test_solve_chain_length_linear():
    # A → B → C → D  =  3 hops
    sg = _subgraph(
        entities=["A", "B", "C", "D"],
        edges=[("A", "B", "D"), ("B", "C", "D"), ("C", "D", "D")],
    )
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert result.max_chain_length == 3


def test_solve_chain_length_isolated_nodes():
    sg = _subgraph(entities=["X", "Y"], edges=[])
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert result.max_chain_length == 0


def test_solve_impact_score_nonnegative():
    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert result.impact_score >= 0.0


def test_solve_has_response_options():
    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert len(result.response_options) >= 1
    assert all(isinstance(o, ResponseOption) for o in result.response_options)


def test_solve_explanation_mentions_event():
    sg = _subgraph(event_id="my-unique-event")
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert "my-unique-event" in result.explanation


def test_solve_explanation_mentions_affected_count():
    sg = _subgraph(entities=["A", "B", "C", "D", "E"])
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert "5" in result.explanation


def test_solve_metadata_identifies_stub():
    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    result = StubSolver().solve(sg, ls)
    assert result.metadata.get("solver") == "stub"


def test_solve_deterministic():
    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    r1 = StubSolver().solve(sg, ls)
    r2 = StubSolver().solve(sg, ls)
    assert r1.impact_score == r2.impact_score
    assert r1.affected_count == r2.affected_count
    assert r1.max_chain_length == r2.max_chain_length


def test_solve_empty_live_state_still_works():
    """Solver must not crash when live_state has no entries."""
    sg = _subgraph()
    result = StubSolver().solve(sg, {})
    assert result.affected_count == len(sg.affected_entity_ids)


# ── Solver tool ───────────────────────────────────────────────────────────────


def test_solver_tool_schema_shape():
    assert SOLVER_TOOL_SCHEMA["type"] == "function"
    fn = SOLVER_TOOL_SCHEMA["function"]
    assert fn["name"] == "solve_impact"
    props = fn["parameters"]["properties"]
    assert "event_id" in props
    assert "scenario_id" in props
    assert fn["parameters"]["required"] == ["event_id", "scenario_id"]


@pytest.mark.asyncio
async def test_call_solver_tool_success():
    sg = _subgraph(event_id="tool-evt", scenario_id="tool-s1",
                   entities=["P", "Q", "R"],
                   edges=[("P", "Q", "D"), ("Q", "R", "D")])
    ls = _live_state(sg.affected_entity_ids)

    result = await call_solver_tool(
        {"event_id": "tool-evt", "scenario_id": "tool-s1"},
        sg,
        ls,
    )

    assert result["success"] is True
    assert result["event_id"] == "tool-evt"
    assert result["affected_count"] == 3
    assert result["max_chain_length"] == 2
    assert isinstance(result["impact_score"], float)
    assert len(result["response_options"]) >= 1
    assert "explanation" in result


@pytest.mark.asyncio
async def test_call_solver_tool_with_injected_solver():
    """Custom solver can be injected — tool doesn't hard-code StubSolver."""

    class AlwaysOneSolver:
        def solve(self, subgraph, live_state):
            from src.core.solver import SolverResult
            return SolverResult(
                event_id=subgraph.event_id,
                affected_count=1,
                max_chain_length=1,
                impact_score=0.5,
                explanation="custom",
            )

    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    result = await call_solver_tool({"event_id": "e", "scenario_id": "s"},
                                    sg, ls, solver=AlwaysOneSolver())
    assert result["affected_count"] == 1
    assert result["explanation"] == "custom"


@pytest.mark.asyncio
async def test_call_solver_tool_error_handled():
    class BrokenSolver:
        def solve(self, subgraph, live_state):
            raise RuntimeError("solver exploded")

    sg = _subgraph()
    ls = _live_state(sg.affected_entity_ids)
    result = await call_solver_tool({}, sg, ls, solver=BrokenSolver())
    assert result["success"] is False
    assert "solver exploded" in result["error"]
