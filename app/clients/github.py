"""Backward-compatible export; integrations now live in app.integrations."""

from app.integrations.github_client import GitHubClient

__all__ = ["GitHubClient"]
