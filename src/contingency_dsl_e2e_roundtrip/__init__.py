"""End-to-end roundtrip harness for contingency-dsl."""

try:
    from ._version import __version__, __version_tuple__  # type: ignore[attr-defined]
except ImportError:  # source checkout without build-time hatch-vcs hook
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "unknown")
