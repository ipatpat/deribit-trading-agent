"""Type-safe enumerations for Deribit API values."""

from enum import StrEnum


class InstrumentKind(StrEnum):
    FUTURE = "future"
    OPTION = "option"
    SPOT = "spot"
    FUTURE_COMBO = "future_combo"
    OPTION_COMBO = "option_combo"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"
    MARKET = "market"
    STOP_LIMIT = "stop_limit"
    STOP_MARKET = "stop_market"
    TAKE_LIMIT = "take_limit"
    TAKE_MARKET = "take_market"
    MARKET_LIMIT = "market_limit"
    TRAILING_STOP = "trailing_stop"


class OrderState(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNTRIGGERED = "untriggered"


class TimeInForce(StrEnum):
    GOOD_TIL_CANCELLED = "good_til_cancelled"
    GOOD_TIL_DAY = "good_til_day"
    FILL_OR_KILL = "fill_or_kill"
    IMMEDIATE_OR_CANCEL = "immediate_or_cancel"


class TriggerType(StrEnum):
    INDEX_PRICE = "index_price"
    MARK_PRICE = "mark_price"
    LAST_PRICE = "last_price"


class Currency(StrEnum):
    BTC = "BTC"
    ETH = "ETH"
    USDC = "USDC"
    USDT = "USDT"
    SOL = "SOL"
