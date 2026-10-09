"""Strict projections of provider contract and risk-query responses."""
import math
import re
from .core import StopRun


def contract(rows, symbol, exchange=None):
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z]{1,6}[0-9]{3,4}", symbol):
        raise StopRun("INVALID_FUTURES_SYMBOL")
    # CTP may return prefix matches, including options. Never trade the first row.
    matches = [d for d in rows if d.get("InstrumentID") == symbol
               and (exchange is None or d.get("ExchangeID") == exchange)]
    if len(matches) != 1:
        raise StopRun("INSTRUMENT_NOT_UNIQUE")
    d = matches[0]
    numbers = [d.get(k, 0) for k in ("PriceTick", "VolumeMultiple")]
    if (d.get("ExchangeID") not in {"SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX"}
            or d.get("ProductClass") != "1" or d.get("IsTrading") != 1
            or not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in numbers)
            or not d.get("MinLimitOrderVolume", 2) <= 1 <= d.get("MaxLimitOrderVolume", 0)):
        raise StopRun("INSTRUMENT_NOT_ELIGIBLE")
    return d


def margin_check(d, quote, margins, commissions, accounts):
    allowed = {d["InstrumentID"], d["ProductID"]}
    def matches(row):
        # Observed CFFEX risk responses leave ExchangeID empty. Require the
        # queried instrument/product; reject any explicit conflicting exchange.
        return row.get("InstrumentID") in allowed and row.get("ExchangeID") in {None, "", d["ExchangeID"]}
    margins = [m for m in margins if matches(m) and m.get("HedgeFlag") == "1"]
    commissions = [m for m in commissions if matches(m)]
    accounts = [a for a in accounts if a.get("CurrencyID", "CNY") == "CNY"]
    if not margins or not commissions or len(accounts) != 1:
        raise StopRun("MARGIN_OR_FEE_QUERY_INCOMPLETE")
    # Intraday fee schedules can differ even when the exchange uses generic
    # CLOSE rather than CLOSE_TODAY in the order. Budget the larger close rate.
    closing = ("CloseTodayRatio", "CloseRatio")
    amounts = [d.get("LongMarginRatio", 0), accounts[0].get("Available", 0)]
    amounts += [m.get(k, 0) for m in margins for k in ("LongMarginRatioByMoney", "LongMarginRatioByVolume")]
    amounts += [f.get(p+s, 0) for f in commissions for p in ("OpenRatio", *closing) for s in ("ByMoney", "ByVolume")]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in amounts):
        raise StopRun("INVALID_RISK_QUERY")
    required = max(quote.upper*d["VolumeMultiple"]*max(m.get("LongMarginRatioByMoney", 0), d.get("LongMarginRatio", 0))
                   + m.get("LongMarginRatioByVolume", 0) for m in margins)
    def charge(f, prefix):
        return quote.upper*d["VolumeMultiple"]*f.get(prefix+"ByMoney", 0)+f.get(prefix+"ByVolume", 0)
    fees = max(charge(f,"OpenRatio")+max(charge(f,p) for p in closing) for f in commissions)
    buffer = 10*d["PriceTick"]*d["VolumeMultiple"]
    if not math.isfinite(required+fees+buffer) or required <= 0 or accounts[0]["Available"] < required*1.1+fees+buffer:
        raise StopRun("INSUFFICIENT_VERIFIED_MARGIN")
    return {"contract_valid": True, "margin_sufficient": True, "fees_queried": True}
