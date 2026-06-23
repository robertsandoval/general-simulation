"""Solver package — pluggable Stage-2 quantitative solver implementations.

Public surface:
    StubSolver          — deterministic placeholder; ships with the MVP.
    SOLVER_TOOL_SCHEMA  — Llama Stack tool schema for solve_impact.
    call_solver_tool    — tool callable for the reasoning orchestrator.
"""
from src.solver.stub import StubSolver
from src.solver.tool import SOLVER_TOOL_SCHEMA, call_solver_tool

__all__ = ["StubSolver", "SOLVER_TOOL_SCHEMA", "call_solver_tool"]
