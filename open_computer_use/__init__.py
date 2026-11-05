"""Native background desktop operations; the model-driven Agent is optional."""

from .desktop import Desktop, StaleWindow

__all__ = ["Agent", "Desktop", "StaleWindow"]
__version__ = "0.1.0"


def __getattr__(name):
    if name == "Agent":
        from .agent import Agent
        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
