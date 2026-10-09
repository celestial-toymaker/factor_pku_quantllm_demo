"""Explicit simulation gate. Defaults never load native libraries or credentials."""
import argparse
from dataclasses import asdict
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import time
from .core import Plan, StopRun
from .market import contract
from .runner import dry_run, run_simnow
from .security import load_private, verify_evidence, write_public


def parser():
    p = argparse.ArgumentParser(prog="ctp-assignment")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("doctor", "inspect", "quotes", "run", "reconcile", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--native-dir", type=Path)
        s.add_argument("--config", type=Path)
        s.add_argument("--output", type=Path)
        if name in {"inspect", "quotes", "run", "reconcile"}:
            s.add_argument("--simnow", action="store_true")
            s.add_argument("--state", type=Path)
        if name == "quotes":
            s.add_argument("--symbols", nargs="+", required=True)
            s.add_argument("--seconds", type=float, default=0)
        elif name == "inspect":
            s.add_argument("--symbols", nargs="+", default=[])
        if name == "verify":
            s.add_argument("evidence", type=Path)
    return p


def execute(a):
    if a.command == "verify":
        return verify_evidence(json.loads(a.evidence.read_text())), 0
    if a.command == "doctor":
        result = {"python": sys.version.split()[0], "network_connections": 0, "native_import": "NOT_REQUESTED"}
        if a.native_dir:
            from .native import load_native
            md, td = load_native(a.native_dir)
            result.update(native_import="PASS", md_version=md.MdApi().getApiVersion(), td_version=td.TdApi().getApiVersion())
        if a.output:
            write_public(a.output, result)
        return result, 0
    if not a.simnow:
        if a.command != "run":
            raise StopRun("EXPLICIT_SIMNOW_FLAG_REQUIRED")
        if not a.state or not a.output:
            raise StopRun("STATE_AND_OUTPUT_REQUIRED")
        e = dry_run(a.state, a.output)
        return verify_evidence(e), 0
    if not a.config or not a.native_dir:
        raise StopRun("PRIVATE_CONFIG_AND_NATIVE_DIRECTORY_REQUIRED")
    cfg = load_private(a.config)
    from .native import Native
    n = Native(a.native_dir, cfg, a.config.resolve().parent / "native-flow")
    if a.command in {"run", "reconcile"}:
        if not a.state or not a.output or a.state.resolve().parent != a.config.resolve().parent:
            raise StopRun("LIVE_JOURNAL_MUST_STAY_IN_PRIVATE_DIRECTORY")
        try:
            p = Plan(cfg["instrument"], cfg["exchange"], float(cfg["trigger_price"]), mode="SIMNOW")
            p.validate()
        except (KeyError, TypeError, ValueError):
            raise StopRun("INSTRUMENT_AND_THRESHOLD_REQUIRED") from None
        e = run_simnow(n, cfg, p, a.state, a.output, a.command == "reconcile")
        return verify_evidence(e), 0 if e["live_acceptance"] == "PASS" else 2
    result = {"mode": "SIMNOW", "orders_sent": 0, "status": "NOT_COMPLETED"}
    try:
        n.connect()
        result["login"] = "PASS"
        result["trading_day"] = n.session["TradingDay"]
        if a.command == "inspect":
            rows = n.query("instrument")
            eligible = [d for d in rows if d.get("ProductClass") == "1" and d.get("IsTrading") == 1
                        and d.get("ProductID") in {"rb", "m", "al", "IF", "T"}
                        and d.get("ExpireDate", "") >= (date.today()+timedelta(days=45)).strftime("%Y%m%d")]
            chosen = []
            for product in ("rb", "m", "al", "IF", "T"):
                chosen.extend(sorted([x for x in eligible if x["ProductID"] == product], key=lambda x:x["ExpireDate"])[:3])
            result["instruments"] = [{k:d.get(k) for k in ("InstrumentID", "ExchangeID", "ProductID", "PriceTick", "VolumeMultiple", "ExpireDate")} for d in chosen]
            if a.symbols:
                result["risk_query_checks"] = {}
                for symbol in a.symbols:
                    d = contract(rows, symbol)
                    n.contracts[symbol] = d
                    margins = n.query("margin", symbol)
                    fees = n.query("commission", symbol)
                    positions = n.query("positions", symbol)
                    result["risk_query_checks"][symbol] = {
                        "exchange": d["ExchangeID"],
                        "continuous_trading": n.market_open(symbol),
                        "margin_instrument_ids": sorted({r.get("InstrumentID", "") for r in margins}),
                        "fee_instrument_ids": sorted({r.get("InstrumentID", "") for r in fees}),
                        "long": sum(r.get("Position",0) for r in positions if r.get("InstrumentID")==symbol and r.get("PosiDirection")=="2"),
                        "short": sum(r.get("Position",0) for r in positions if r.get("InstrumentID")==symbol and r.get("PosiDirection")=="3")}
                accounts = n.query("account")
                orders = n.query("orders")
                result["one_cny_account_returned"] = len([d for d in accounts if d.get("CurrencyID")=="CNY"]) == 1
                result["active_orders"] = sum(d.get("OrderStatus") not in {"0","2","4","5"} and d.get("OrderSubmitStatus")!="4" for d in orders)
            n.drain(0.1)
            result["market_status_counts"] = {s:sum(v==s for v in n.market_status.values()) for s in sorted(set(n.market_status.values()))}
            result["continuous_trading_products"] = sorted([".".join(k) for k,v in n.market_status.items() if v=="2"])
            result["status"] = "METADATA_QUERIED"
        else:
            result["contract_queries"] = {}
            for symbol in a.symbols:
                rows = n.query("instrument", symbol)
                n.contracts[symbol] = contract(rows, symbol)
                result["contract_queries"][symbol] = {"returned_rows": len(rows), "exact_match": True}
            n.subscribe(a.symbols)
            start = time.monotonic()
            seen = {}
            result["ticks"] = {s:0 for s in a.symbols}
            result["last_quotes"] = {}
            while a.seconds == 0 or time.monotonic()-start < a.seconds:
                n.drain(0.25)
                for symbol in a.symbols:
                    q = n.quote(symbol)
                    if q and seen.get(symbol) != q.received:
                        seen[symbol] = q.received
                        result["ticks"][symbol] += 1
                        projection = {"instrument": symbol, "last": q.last, "bid": q.bid, "ask": q.ask,
                                      "lower_limit": q.lower, "upper_limit": q.upper,
                                      "source_age_seconds": round(q.source_age, 3),
                                      "continuous_trading": n.market_open(symbol),
                                      "fresh": q.valid(time.monotonic(), 3), "tick": q.tick}
                        result["last_quotes"][symbol] = projection
                        print(json.dumps(projection, allow_nan=False), flush=True)
            result["subscription_callbacks"] = n.subscription_count
            for symbol in a.symbols:
                q = n.quote(symbol)
                if q and symbol in result["last_quotes"]:
                    result["last_quotes"][symbol]["fresh"] = q.valid(time.monotonic(), 3)
            result["status"] = "QUOTES_RECEIVED" if all(result["ticks"].values()) else "NO_COMPLETE_QUOTE_EVIDENCE"
            result["all_last_quotes_fresh"] = len(result["last_quotes"]) == len(a.symbols) and all(q["fresh"] for q in result["last_quotes"].values())
    except KeyboardInterrupt:
        result["status"] = "QUOTE_STREAM_STOPPED_BY_USER"
    except StopRun as exc:
        result.update(status="BLOCKED", reason=str(exc))
    finally:
        n.close()
        result["last_completed_or_pending_stage"] = n.phase
        result["callback_trace"] = n.trace
        if a.output:
            write_public(a.output, result, cfg)
    return result, 0 if result["status"] in {"METADATA_QUERIED", "QUOTES_RECEIVED", "QUOTE_STREAM_STOPPED_BY_USER"} else 2


def main():
    a = parser().parse_args()
    try:
        result, code = execute(a)
    except StopRun as exc:
        result, code = {"status": "BLOCKED", "reason": str(exc)}, 2
    except Exception as exc:
        # Do not print exception messages containing native request dictionaries.
        result, code = {"status": "ERROR", "error_type": type(exc).__name__}, 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
