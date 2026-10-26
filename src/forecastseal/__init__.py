"""forecastseal: seal the plan, append forecasts, resolve outcomes, verify the chain."""
from .ledger import Ledger, LedgerError, canonical, entry_hash

__all__ = ["Ledger", "LedgerError", "canonical", "entry_hash"]
__version__ = "0.0.1"
