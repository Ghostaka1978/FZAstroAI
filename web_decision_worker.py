"""Compatibility wrapper for the relocated web decision worker."""

from .workers.web_decision_worker import WebDecisionWorker, parse_web_decision

__all__ = ["WebDecisionWorker", "parse_web_decision"]
