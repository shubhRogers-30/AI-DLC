"""Backward-compatible export; Copilot integration now lives in app.agents."""

from app.agents.copilot_service import CopilotService

__all__ = ["CopilotService"]
