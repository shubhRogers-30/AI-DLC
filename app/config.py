"""Backward-compatible exports; configuration now lives in app.core.config."""

from app.core.config import Settings, settings

__all__ = ["Settings", "settings"]
