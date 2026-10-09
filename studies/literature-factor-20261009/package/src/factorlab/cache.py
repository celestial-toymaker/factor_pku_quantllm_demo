"""Parse the supplied cache as data, never call pickle.load or source code."""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
import pickletools
import re
import pandas as pd
import pyarrow as pa
from .common import digest, dump, now

def read_membership(path):
    """Tiny allowlisted interpreter; GLOBAL/REDUCE never resolve Python objects.

    Only dict-of-lists-of-datetime-pairs is accepted. Date bytes are decoded
    manually. Unrecognized opcodes or constructor markers are rejected.
    """
    stack, memo = [], {}
    mark = object()
    for op, arg, _ in pickletools.genops(Path(path).read_bytes()):
        name = op.name
        if name in {"PROTO", "FRAME"}:
            continue
        if name in {"SHORT_BINUNICODE", "BINUNICODE", "SHORT_BINBYTES", "BINBYTES"}:
            stack.append(arg)
        elif name == "MEMOIZE":
            memo[len(memo)] = stack[-1]
        elif name in {"BINGET", "LONG_BINGET"}:
            stack.append(memo[arg])
        elif name == "STACK_GLOBAL":
            item, module = stack.pop(), stack.pop()
            if (module, item) not in {("datetime", "datetime"), ("collections", "defaultdict"), ("builtins", "list")}:
                raise ValueError("Forbidden pickle constructor")
            stack.append(("constructor", module, item))
        elif name in {"TUPLE1", "TUPLE2"}:
            n = int(name[-1]); items = stack[-n:]; del stack[-n:]
            stack.append(tuple(items))
        elif name == "REDUCE":
            args, kind = stack.pop(), stack.pop()
            if kind == ("constructor", "collections", "defaultdict") and args == (("constructor", "builtins", "list"),):
                stack.append({})
            elif kind == ("constructor", "datetime", "datetime") and len(args) == 1 and isinstance(args[0], bytes) and len(args[0]) == 10:
                b = args[0]
                stack.append(datetime(int.from_bytes(b[:2], "big"), b[2] & 127, b[3], b[4], b[5], b[6], int.from_bytes(b[7:], "big")))
            else:
                raise ValueError("Forbidden pickle reduction")
        elif name == "EMPTY_LIST":
            stack.append([])
        elif name == "MARK":
            stack.append(mark)
        elif name == "APPEND":
            v = stack.pop(); stack[-1].append(v)
        elif name in {"APPENDS", "SETITEMS"}:
            i = next(i for i in range(len(stack)-1, -1, -1) if stack[i] is mark)
            items = stack[i+1:]; del stack[i:]
            if name == "APPENDS":
                stack[-1].extend(items)
            else:
                if len(items) % 2: raise ValueError("Odd dictionary items")
                stack[-1].update(zip(items[::2], items[1::2]))
        elif name == "STOP":
            break
        else:
            raise ValueError(f"Unsupported pickle opcode {name}")
    if len(stack) != 1 or not isinstance(stack[0], dict):
        raise ValueError("Unexpected membership object")
    rows = []
    for symbol, intervals in stack[0].items():
        if not re.fullmatch(r"\d{6}\.(SSE|SZSE)", symbol): raise ValueError("Bad symbol")
        for start, end in intervals:
            if not isinstance(start, datetime) or not isinstance(end, datetime) or start > end:
                raise ValueError("Invalid membership interval")
            rows.append({"symbol": symbol, "start": start, "end": end})
    return pd.DataFrame(rows)

def extract_prices(path):
    payload = Path(path).read_bytes()
    for op, arg, _ in pickletools.genops(payload):
        if op.name in {"BINBYTES", "BINBYTES8"} and len(arg) > 1_000_000:
            try:
                table = pa.ipc.open_stream(arg).read_all()
            except pa.ArrowInvalid:
                continue
            if {"datetime", "vt_symbol", "open", "close", "volume", "turnover"}.issubset(table.column_names):
                idx = table.column_names.index("vt_symbol")
                table = table.set_column(idx, "vt_symbol", table["vt_symbol"].cast(pa.string()))
                return table.to_pandas().rename(columns={"datetime": "date", "vt_symbol": "symbol", "turnover": "amount"})
    raise ValueError("No recognized Arrow panel in cache")

def membership_mask(prices, intervals):
    eligible = pd.Series(False, index=prices.index)
    indices = prices.groupby("symbol", sort=False).groups
    for symbol, records in intervals.groupby("symbol"):
        ix = indices.get(symbol)
        if ix is None: continue
        dates = prices.loc[ix, "date"]
        selected = pd.Series(False, index=ix)
        for rec in records.itertuples():
            selected |= dates.between(rec.start, rec.end)
        eligible.loc[ix] = selected
    return eligible

def audit_cache(root, cache_dir):
    root, cache_dir = Path(root), Path(cache_dir)
    p, f = cache_dir / "base_dataset.pkl", cache_dir / "filters.pkl"
    frame = extract_prices(p).sort_values(["date", "symbol"]).reset_index(drop=True)
    memberships = read_membership(f)
    frame["eligible_member"] = membership_mask(frame, memberships)
    out = root / "private" / "course"
    out.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out / "prices.parquet", index=False)
    memberships.to_csv(out / "membership.csv", index=False)
    counts = frame.loc[frame.eligible_member].groupby("date").symbol.nunique()
    raw_returns = frame.sort_values(["symbol", "date"]).groupby("symbol").close.pct_change(fill_method=None)
    raw_checks = {
        "rows": len(frame), "symbols": int(frame.symbol.nunique()),
        "min_date": str(frame.date.min().date()), "max_date": str(frame.date.max().date()),
        "duplicates": int(frame.duplicated(["date", "symbol"]).sum()),
        "membership_intervals": len(memberships), "member_count_min": int(counts.min()),
        "member_count_median": float(counts.median()), "member_count_max": int(counts.max()),
        "missing_by_field": frame.isna().sum().to_dict(),
        "nonpositive_ohlc_rows": int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "nonpositive_volume_rows": int((frame.volume <= 0).sum()),
        "absolute_next_stored_price_jump_over_25pct": int((raw_returns.abs() > .25).sum()),
        "ohlc_subcent_fraction": float(((frame.close * 100 - (frame.close * 100).round()).abs() > 1e-5).mean()),
        "monetary_amount_over_volume_close_quantiles": (frame.amount / frame.volume / frame.close).quantile([.01,.5,.99]).to_dict(),
    }
    manifest = {"created_utc": now(), "source": "user-supplied workshop cache", "license": "research input; redistribution not established; excluded from archive", "files": [{"role": role, "path": str(path), "sha256": digest(path)} for role,path in [("course_cache",p),("membership",f)]], "audit": raw_checks,
                "integrity": {"adjustment_convention": "unverified", "raw_executable_prices": "unverified", "corporate_action_cash_flows": "missing", "historical_trading_status": "missing", "historical_st_status": "missing", "daily_limit_prices": "missing", "point_in_time_industry": "missing", "security_listing_delisting_dates": "missing"}}
    dump(root / "data/data_manifest.json", manifest)
    dump(root / "results/data_audit.json", raw_checks)
    return manifest
