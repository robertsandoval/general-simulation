"""Shared domain types for the Llama Stack client surface.

These are thin, SDK-agnostic data classes.  The real LlamaStackClient wrapper
converts between these and the llama-stack-client SDK types internally, so the
rest of the app never imports from llama_stack_client directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """A single turn in a conversation."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass
class ToolCall:
    """A structured tool invocation requested by the model."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class GenerateResult:
    """Result of a single inference.chat_completion call."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_of_turn"


@dataclass
class Chunk:
    """A retrieved text chunk from a vector search."""

    document_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
