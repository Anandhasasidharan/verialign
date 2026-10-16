"""Interactive verification console for VeriAlign.

The ``.app`` submodule (and ``textual``) are intentionally NOT imported here, so
that ``import verialign.tui`` and ``import verialign.tui.data`` work in an
environment without the optional ``tui`` extra installed. Callers read the
data layer via ``verialign.tui.data`` and launch the app lazily with::

    from verialign.tui.app import run_tui
"""

__all__ = ["data"]
