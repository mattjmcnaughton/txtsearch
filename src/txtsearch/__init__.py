"""txtsearch - A CLI tool for searching text files with advanced pattern matching."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("txtsearch")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["__version__"]
