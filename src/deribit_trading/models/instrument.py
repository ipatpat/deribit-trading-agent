"""Instrument model for tradable instruments on Deribit."""

from datetime import datetime

from pydantic import BaseModel

from .enums import InstrumentKind, OptionType


class Instrument(BaseModel, extra="ignore"):
    """A tradable instrument on Deribit."""

    instrument_name: str
    kind: InstrumentKind
    base_currency: str
    quote_currency: str
    settlement_currency: str | None = None
    contract_size: float
    is_active: bool
    tick_size: float
    min_trade_amount: float

    # Futures / options fields
    expiration_timestamp: int | None = None
    creation_timestamp: int | None = None

    # Option-specific fields
    strike: float | None = None
    option_type: OptionType | None = None

    @property
    def expiry(self) -> datetime | None:
        if self.expiration_timestamp is not None:
            return datetime.fromtimestamp(self.expiration_timestamp / 1000)
        return None

    @property
    def is_perpetual(self) -> bool:
        return self.kind == InstrumentKind.FUTURE and self.expiration_timestamp is None

    @property
    def is_option(self) -> bool:
        return self.kind == InstrumentKind.OPTION
