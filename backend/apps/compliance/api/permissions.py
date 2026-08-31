"""Who may reach the analysis endpoints.

The class itself now lives in `apps.core.api.permissions`, because three apps
guard endpoints with it and only one of them is this one - see that module for
the reasoning and for what the demo switch does and does not relax.

Re-exported here rather than moved outright: `docs/api.md`, `config/settings.py`
and existing tests all name this path, and a rename with no behavioural change
is not worth breaking them over.
"""

from __future__ import annotations

from apps.core.api.permissions import IsAuthenticatedOrDemoPublic

__all__ = ["IsAuthenticatedOrDemoPublic"]
