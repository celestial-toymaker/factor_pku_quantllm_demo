"""Orchestrate the same controller with a synthetic or native adapter."""
from dataclasses import asdict
from pathlib import Path
import time
from .core import Controller, Journal, Plan, Quote, StopRun
from .security import binding, write_public, verify_evidence
from .market import contract, margin_check


def dry_run(state, output):
    plan = Plan("SYNTHETIC", "SHFE", 100.0)
    now = [1000.0]
    clock = lambda: now[0]
    j = Journal(Path(state), plan, "SYNTHETIC", clock)
    c = Controller(j, plan, clock)
    try:
        c.session_ready(1, 2, 0, "SYNTHETIC_DAY")
        proof = {"completed": ["orders", "trades", "positions"], "day": c.day,
                 "session": 2, "started": now[0], "stable": True,
                 "long": 0, "short": 0, "active_orders": 0, "preflight_ok": True}
        c.reconcile(proof)
        c.tick(Quote("SYNTHETIC", 101, 100, 101, 90, 110, now[0], 0, 1))
        for leg, price in (("OPEN", 101), ("CLOSE", 100)):
            actions = c.take_actions()
            if not actions:
                raise StopRun("DRY_RUN_REQUIRES_FRESH_JOURNAL")
            a = actions[0]
            assert a["leg"] == leg
            c.order(a["ref"], 1, 2, "S"+a["ref"], "FILLED", 1, plan.instrument, 1)
            now[0] += 0.1
            c.trade("SYNTHETIC_"+leg, a["ref"], 1, price, leg, plan.instrument)
        c.reconcile({**proof, "started": now[0]+0.1})
        e = c.evidence()
        # Independently reproducible arithmetic: buy 101, sell 100, multiplier 10,
        # fee 2 per side => gross -10, total fees 4, net -14.
        e["hand_calculated_example"] = {"multiplier": 10, "gross_pnl": -10,
                                        "fees": 4, "net_pnl": -14, "source": "synthetic"}
        verify_evidence(e)
        write_public(output, e)
        return e
    finally:
        j.close()


class LiveRunner:
    def __init__(self, native, controller):
        self.n = native
        self.c = controller
        self.waiting_trades = []
        self.mutation = 0

    def order(self, d):
        status = {"0": "FILLED", "1": "WORKING", "2": "CANCELLED", "3": "WORKING",
                  "4": "CANCELLED", "5": "CANCELLED", "a": "SUBMITTING", "b": "SUBMITTING", "c": "SUBMITTING"}.get(d.get("OrderStatus"))
        if d.get("OrderSubmitStatus") == "4":
            status = "REJECTED"
        if status is None:
            self.c.fault("UNRECOGNIZED_ORDER_STATUS")
            return
        own = self.c.order(str(d.get("OrderRef", "")).strip(), d.get("FrontID"), d.get("SessionID"),
                           str(d.get("OrderSysID", "")).strip(), status, d.get("VolumeTraded"),
                           d.get("InstrumentID"), d.get("VolumeTotalOriginal"))
        if not own and status not in self.c.TERMINAL:
            self.c.fault("UNOWNED_ACTIVE_ORDER")

    def trade(self, d):
        sysid = str(d.get("OrderSysID", "")).strip()
        own = next((o for o in self.c.j.orders() if o["sysid"] and o["sysid"] == sysid
                    and d.get("ExchangeID") == self.c.plan.exchange
                    and str(d.get("OrderRef", "")).strip() == o["ref"]), None)
        if not own:
            return False
        expected_dir = "0" if own["leg"] == "OPEN" else "1"
        if (d.get("TradingDay") != self.c.day or d.get("Direction") != expected_dir
                or d.get("OffsetFlag") != {"OPEN": "0", "CLOSE": "1", "CLOSE_TODAY": "3"}[own["offset"]]):
            self.c.fault("TRADE_ATTRIBUTION_MISMATCH")
            return True
        key = "|".join((d["ExchangeID"], d["TradingDay"], str(d["TradeID"]).strip()))
        self.c.trade(key, own["ref"], d["Volume"], d["Price"], own["leg"], d["InstrumentID"])
        return True

    def events(self, events):
        for side, name, args, received in events:
            if name == "onRtnOrder":
                self.mutation += 1
                self.order(args[0])
            elif name == "onRtnTrade":
                self.mutation += 1
                self.waiting_trades.append(args[0])
            elif name in {"onRspOrderInsert", "onErrRtnOrderInsert", "onRspOrderAction", "onErrRtnOrderAction"}:
                if len(args) >= 2 and args[1].get("ErrorID", 0):
                    self.c.fault("ORDER_OR_CANCEL_REJECTED")
        self.waiting_trades = [t for t in self.waiting_trades if not self.trade(t)]

    def actions(self):
        for a in self.c.take_actions():
            if a["action"] == "send":
                self.n.send(a, self.c.plan)
            else:
                self.n.cancel(a, self.c.plan)

    def snapshot(self, preflight_ok=False):
        self.c.reconciled = False
        self.c.can_open = False
        self.events(self.n.drain(0))
        start = time.monotonic()
        revision = self.mutation
        orders = self.n.query("orders")
        for o in orders:
            self.order(o)
        trades = self.n.query("trades")
        for t in trades:
            self.trade(t)
        positions = self.n.query("positions", self.c.plan.instrument)
        self.events(self.n.drain(0))
        active = sum(o.get("OrderStatus") not in {"0", "2", "4", "5"} and o.get("OrderSubmitStatus") != "4" for o in orders)
        pos = [p for p in positions if p.get("InstrumentID") == self.c.plan.instrument]
        if any(p.get("PosiDirection") not in {"2", "3"} or p.get("HedgeFlag") != "1" for p in pos):
            raise StopRun("UNSUPPORTED_POSITION_TYPE")
        proof = {"completed": ["orders", "trades", "positions"], "day": self.c.day,
                 "session": self.c.session, "started": start, "stable": revision == self.mutation,
                 "long": sum(p.get("Position", 0) for p in pos if p.get("PosiDirection") == "2"),
                 "short": sum(p.get("Position", 0) for p in pos if p.get("PosiDirection") == "3"),
                 "active_orders": active, "preflight_ok": preflight_ok}
        return self.c.reconcile(proof)

    def preflight(self):
        p = self.c.plan
        rows = self.n.query("instrument", p.instrument)
        d = contract(rows, p.instrument, p.exchange)
        self.n.contracts[p.instrument] = d
        self.n.subscribe([p.instrument])
        end = time.monotonic()+15
        while time.monotonic() < end:
            self.events(self.n.drain(0.25))
            q = self.n.quote(p.instrument)
            if q and q.valid(time.monotonic(), p.quote_age, p.source_future_tolerance) and self.n.market_open(p.instrument):
                break
        else:
            raise StopRun("NO_OPEN_MARKET_WITH_FRESH_QUOTE")
        margins = self.n.query("margin", p.instrument)
        commissions = self.n.query("commission", p.instrument)
        accounts = self.n.query("account")
        self.c.j.event("preflight", margin_check(d, q, margins, commissions, accounts))
        self.snapshot(True)


def run_simnow(native, cfg, plan, state, output, reconcile_only=False):
    j = Journal(Path(state), plan, binding(cfg))
    c = Controller(j, plan)
    c.allow_orders = not reconcile_only
    r = LiveRunner(native, c)
    reason = None
    try:
        native.connect()
        s = native.session
        c.session_ready(s["FrontID"], s["SessionID"], s["MaxOrderRef"], s["TradingDay"])
        if reconcile_only:
            # Reconciliation command is strictly read-only: do not price or
            # dispatch recovery actions. It reports remaining exposure.
            r.snapshot(False)
        else:
            r.preflight()
            deadline = time.monotonic()+plan.run_timeout
            last_snapshot = time.monotonic()
            while time.monotonic() < deadline:
                r.events(native.drain(0.15))
                q = native.quote(plan.instrument)
                if q and native.market_open(plan.instrument):
                    c.tick(q)
                elif c.can_open:
                    c.fault("MARKET_NOT_CONTINUOUS")
                c.timeouts()
                r.actions()
                state_now = j.get("state")
                if state_now in {"PASS", "OFFLINE_PASS", "NO_OPEN_FILL"}:
                    break
                totals = j.totals()
                if (totals["CLOSE"] == 1 or state_now == "RECONCILE_REQUIRED"
                        or state_now == "ARMED" and time.monotonic() > c.armed_until):
                    if time.monotonic()-last_snapshot > 1.2:
                        # Do not silently re-arm an expired preflight. Re-run
                        # margin/metadata verification before any first order.
                        if state_now == "ARMED":
                            r.preflight()
                        else:
                            r.snapshot(False)
                        last_snapshot = time.monotonic()
            if j.get("state") not in {"PASS", "OFFLINE_PASS"}:
                c.fault("RUN_DEADLINE_OR_UNFINISHED")
                r.actions()
                # One bounded cancellation/reconciliation grace; no new opening.
                for _ in range(3):
                    r.events(native.drain(1.0))
                    r.snapshot(False)
                    q = native.quote(plan.instrument)
                    if q:
                        c.tick(q)
                    r.actions()
                    if j.get("state") in {"PASS", "OFFLINE_PASS", "NO_OPEN_FILL"}:
                        break
    except (Exception, KeyboardInterrupt) as exc:
        reason = (str(exc) if isinstance(exc, StopRun) else "INTERRUPTED"
                  if isinstance(exc, KeyboardInterrupt) else "UNEXPECTED_"+type(exc).__name__)
        if reason in {"CONNECTION_OR_HEARTBEAT_LOST", "CTP_REQUEST_TIMEOUT", "ORDER_SEND_RESULT_UNKNOWN", "CANCEL_SEND_RESULT_UNKNOWN"}:
            c.connected = False
        c.fault(reason)
        try:
            if not reconcile_only:
                r.actions()
        except Exception:
            c.disconnected()
    finally:
        cleanup_error = None
        try:
            native.close()
        except Exception as exc:
            cleanup_error = type(exc).__name__
        try:
            e = c.evidence()
            e["reason"] = reason
            e["cleanup_error_type"] = cleanup_error
            e["execution_kind"] = "read_only_reconciliation" if reconcile_only else "bounded_simnow_run"
            e["callback_trace"] = getattr(native, "trace", [])
            verify_evidence(e)
            write_public(output, e, cfg)
        finally:
            j.close()
    return e
