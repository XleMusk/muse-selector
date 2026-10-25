"""Muse selector package metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


try:
    # Prefer installed distribution metadata so commands report the package
    # version that the entrypoint actually runs.
    __version__ = version("muse-agent")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.1.0"


__all__ = ["__version__"]

