"""AI provider layer: LLM / image / video / voice providers behind ABCs.

Free-first architecture (spec §26): LOCAL → FREE → PAID fallback chains are
defined in ``config.providers``; concrete implementations land phase by phase.
"""
