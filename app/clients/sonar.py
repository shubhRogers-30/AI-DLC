"""Backward-compatible export; integrations now live in app.integrations."""

from app.integrations.sonarqube_client import SonarClient

__all__ = ["SonarClient"]
