"""Elara's tools. Importing this package registers everything on the registry."""

from .registry import registry

from . import apps  # noqa: E402,F401
from . import browser  # noqa: E402,F401
from . import files  # noqa: E402,F401
from . import memory_tools  # noqa: E402,F401
from . import steam  # noqa: E402,F401
from . import system  # noqa: E402,F401
from . import uia  # noqa: E402,F401
from . import websearch  # noqa: E402,F401

__all__ = ["registry"]
