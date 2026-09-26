"""Invoice vertical (E1): folder of PDFs -> verified ledger + anomalies.

Every value written to the ledger exists inside a verbatim quote from the source
PDF, or the row is flagged. No invented values, no fabricated zeros.
"""

from __future__ import annotations

from .pipeline import run_vertical
from .schema import CORE_FIELDS

__all__ = ["CORE_FIELDS", "run_vertical"]
