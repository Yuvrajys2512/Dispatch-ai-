"""Call simulator — drives synthetic calls through the live Phase 4 pipeline.

See :mod:`app.simulator.runner` for the API (:class:`CallSimulator` /
:func:`simulate`) and ``python -m app.simulator`` for the CLI demo.
"""

from app.simulator.runner import CallSimulator, simulate

__all__ = ["CallSimulator", "simulate"]
