"""Llama Stack client package.

Public API:
    get_llama_stack_client(settings) -> LlamaStackClientBase
    LlamaStackClientBase  (Protocol — use for type hints)
    Message, GenerateResult, ToolCall, Chunk  (data types)
"""
from src.llamastack.base import LlamaStackClientBase
from src.llamastack.factory import get_llama_stack_client
from src.llamastack.types import Chunk, GenerateResult, Message, ToolCall

__all__ = [
    "get_llama_stack_client",
    "LlamaStackClientBase",
    "Message",
    "GenerateResult",
    "ToolCall",
    "Chunk",
]
