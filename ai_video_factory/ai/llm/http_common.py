"""LLM HTTP helpers — thin re-export from the shared provider HTTP layer.

Kept as a module so existing imports (``ai.llm.http_common``) stay stable.
"""

from ai_video_factory.ai.http_common import parse_openai_choice, request_json

__all__ = ["parse_openai_choice", "request_json"]
