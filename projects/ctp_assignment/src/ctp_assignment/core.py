"""Durable one-lot controller; no SDK imports and no network operations."""
from dataclasses import dataclass, asdict
import fcntl
import hashlib
import json
import math
import re
from pathlib import Path
import sqlite3
import time


class StopRun(RuntimeError):
    """A fixed, credential-free reason requiring reconciliation or intervention."""


@dataclass(frozen=True)
class Plan:
    instrument: str
    exchange: str
    trigger_price: float
    mode: str = "DRY_RUN"
    quantity: int = 1
    quote_age: float = 3.0
    source_future_tolerance: float = 1.0
    order_timeout: float = 10.0
    cancel_timeout: float = 10.0
    run_timeout: float = 120.0
    max_close_attempts: int = 3

    def validate(self):
        if (not self.instrument or self.exchange not in {"SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX"}
                or self.mode not in {"DRY_RUN", "SIMNOW"} or self.quantity != 1
                or not math.isfinite(self.trigger_price) or self.trigger_price <= 0
                or not all(math.isfinite(x) and x > 0 for x in (self.quote_age, self.order_timeout, self.cancel_timeout, self.run_timeout))
                or not math.isfinite(self.source_future_tolerance) or not 0 <= self.source_future_tolerance <= 1
                or self.mode == "SIMNOW" and not re.fullmatch(r"[A-Za-z]{1,6}[0-9]{3,4}", self.instrument)
                or not 1 <= self.max_close_attempts <= 3):
            raise StopRun("INVALID_PLAN")


@dataclass(frozen=True)
class Quote:
    instrument: str
    last: float
    bid: float
    ask: float
    lower: float
    upper: float
    received: float
    source_age: float
    tick: float

    def valid(self, now, max_age, source_future_tolerance=1.0):
        vals = (self.last, self.bid, self.ask, self.lower, self.upper, self.tick)
        return (all(math.isfinite(x) and 0 < x < 1e12 for x in vals)
                and self.lower <= self.bid <= self.ask <= self.upper
                and self.lower <= self.last <= self.upper
                and 0 <= now-self.received <= max_age and -source_future_tolerance <= self.source_age <= max_age)


class Journal:
    """One exclusive account journal; SQL commits precede every emitted order."""
    def __init__(self, path: Path, plan: Plan, binding: str, clock=time.monotonic):
        plan.validate()
        self.clock = clock
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (path.parent / "account.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise StopRun("ANOTHER_PROCESS_OWNS_ACCOUNT") from None
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS orders(ref TEXT PRIMARY KEY, leg TEXT, volume INTEGER,
                price REAL, offset TEXT, front INTEGER, session INTEGER, sysid TEXT,
                status TEXT, reported INTEGER, sent REAL, cancel_sent REAL);
            CREATE TABLE IF NOT EXISTS fills(key TEXT PRIMARY KEY, ref TEXT, volume INTEGER,
                price REAL, leg TEXT);
        ''')
        digest = hashlib.sha256(json.dumps(asdict(plan), sort_keys=True).encode()).hexdigest()
        old = self.get("plan_hash")
        if old and (old != digest or self.get("binding") != binding):
            self.close()
            raise StopRun("JOURNAL_BINDING_OR_PLAN_CHANGED")
        self.set("plan_hash", digest)
        self.set("binding", binding)
        self.set("plan", asdict(plan))
        if not old:
            self.set("state", "NEW")
            self.event("plan_frozen", {"plan_hash": digest, "mode": plan.mode})
        else:
            self.set("state", "RECONCILE_REQUIRED")
            self.event("restart", {})

    def get(self, k, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, k, v):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))

    def event(self, kind, data):
        with self.db:
            self.db.execute("INSERT INTO events(kind,data) VALUES(?,?)", (kind, json.dumps(data)))

    def orders(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM orders ORDER BY rowid")]

    def totals(self):
        return {leg: self.db.execute("SELECT COALESCE(SUM(volume),0) FROM fills WHERE leg=?", (leg,)).fetchone()[0]
                for leg in ("OPEN", "CLOSE")}

    def close(self):
        self.db.close()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


class Controller:
    TERMINAL = {"FILLED", "CANCELLED", "REJECTED"}

    def __init__(self, journal: Journal, plan: Plan, clock=time.monotonic):
        self.j = journal
        self.plan = plan
        self.clock = clock
        self.actions = []
        self.quote = None
        self.armed_until = 0
        self.front = self.session = 0
        self.next_ref = 0
        self.connected = False
        self.reconciled = False
        self.can_open = False
        self.day = ""
        self.allow_orders = True

    def session_ready(self, front, session, max_ref, day):
        self.front, self.session = int(front), int(session)
        self.next_ref = max(int(max_ref or 0), max([int(x["ref"]) for x in self.j.orders()] or [0]))
        prior = self.j.get("trading_day")
        if prior and prior != day and self.j.orders():
            self.fault("TRADING_DAY_CHANGED")
            raise StopRun("TRADING_DAY_CHANGED")
        self.day = day
        self.j.set("trading_day", day)
        self.connected = True
        self.j.event("session_ready", {"trading_day": day})

    def fault(self, reason):
        self.can_open = False
        self.armed_until = 0
        self.reconciled = False
        self.j.set("state", "RECONCILE_REQUIRED")
        self.j.event("stopped", {"reason": reason})
        # Requests still in the local outbox have not reached the adapter.
        # Cancel them locally; never send them after a failure or disconnect.
        for a in self.actions:
            if a["action"] == "send":
                with self.j.db:
                    self.j.db.execute("UPDATE orders SET status='REJECTED' WHERE ref=?", (a["ref"],))
                self.j.event("local_send_aborted", {"ref": a["ref"]})
        self.actions = [a for a in self.actions if a["action"] != "send"]
        # Cancellation only uses orders already attributed to this run.
        if self.connected:
            for o in self.j.orders():
                if o["status"] not in self.TERMINAL and o["cancel_sent"] is None:
                    self.cancel(o)

    def disconnected(self):
        self.connected = False
        self.fault("DISCONNECTED")

    def cancel(self, order):
        with self.j.db:
            self.j.db.execute("UPDATE orders SET cancel_sent=? WHERE ref=?", (self.clock(), order["ref"]))
        self.actions.append({"action": "cancel", **order})
        self.j.event("cancel_intent", {"ref": order["ref"]})

    def reconcile(self, proof):
        """Accept only complete, same-session, current-day queried evidence."""
        required = {"orders", "trades", "positions"}
        if (not self.connected or set(proof.get("completed", [])) != required
                or proof.get("day") != self.day or proof.get("session") != self.session
                or proof.get("started", -1) < self.j.get("last_fill_time", -1)
                or not proof.get("stable") or proof.get("active_orders", 1) != 0):
            self.fault("INCOMPLETE_OR_ACTIVE_RECONCILIATION")
            return False
        totals = self.j.totals()
        if (proof.get("long") != totals["OPEN"]-totals["CLOSE"] or proof.get("short") != 0
                or not 0 <= totals["CLOSE"] <= totals["OPEN"] <= 1):
            self.fault("POSITION_LEDGER_MISMATCH")
            return False
        if any(o["status"] not in self.TERMINAL for o in self.j.orders()):
            self.fault("OWN_ORDER_STATE_UNKNOWN")
            return False
        for o in self.j.orders():
            n = self.j.db.execute("SELECT COALESCE(SUM(volume),0) FROM fills WHERE ref=?", (o["ref"],)).fetchone()[0]
            if o["reported"] != n:
                self.fault("FILL_REPORT_MISMATCH")
                return False
        self.reconciled = True
        self.j.event("reconciled", {k: proof[k] for k in ("completed", "long", "short", "active_orders", "stable")})
        if totals == {"OPEN": 1, "CLOSE": 1}:
            self.j.set("state", "PASS" if self.plan.mode == "SIMNOW" else "OFFLINE_PASS")
            return True
        if totals["OPEN"] == 1:
            self.j.set("state", "CLOSING")
            self.maybe_close()
        elif not self.j.orders() and not self.j.get("opening_intent"):
            if not proof.get("preflight_ok"):
                self.fault("PREFLIGHT_FAILED")
                return False
            self.can_open = True
            self.armed_until = self.clock()+15
            self.j.set("state", "ARMED")
        else:
            self.j.set("state", "NO_OPEN_FILL")
        return True

    def tick(self, q: Quote):
        if q.instrument != self.plan.instrument:
            return
        self.quote = q
        if not q.valid(self.clock(), self.plan.quote_age, self.plan.source_future_tolerance):
            return
        if (self.can_open and self.reconciled and self.clock() <= self.armed_until
                and q.last > self.plan.trigger_price and not self.j.get("opening_intent")):
            self.submit("OPEN", q.ask, "OPEN")
        self.maybe_close()

    def submit(self, leg, price, offset):
        if not self.allow_orders or not self.connected or not self.quote or not self.quote.valid(self.clock(), self.plan.quote_age, self.plan.source_future_tolerance):
            return
        if leg == "OPEN" and (self.j.get("opening_intent") or not self.can_open):
            return
        if leg == "CLOSE":
            if not self.reconciled or self.j.totals() != {"OPEN": 1, "CLOSE": 0}:
                return
            prior = [o for o in self.j.orders() if o["leg"] == "CLOSE"]
            if len(prior) >= self.plan.max_close_attempts:
                self.fault("CLOSE_ATTEMPTS_EXHAUSTED")
                return
        # Round to the instrument's valid price increment, then re-check bands.
        price = round(round(price / self.quote.tick) * self.quote.tick, 10)
        if not self.quote.lower <= price <= self.quote.upper:
            self.fault("INVALID_LIMIT_PRICE")
            return
        self.next_ref += 1
        ref = str(self.next_ref)
        if len(ref) > 12:
            raise StopRun("ORDER_REFERENCE_EXHAUSTED")
        with self.j.db:
            if leg == "OPEN":
                self.j.db.execute("INSERT OR REPLACE INTO meta VALUES('opening_intent','true')")
            self.j.db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                              (ref, leg, 1, price, offset, self.front, self.session, "", "SUBMITTING", 0, self.clock(), None))
            self.j.db.execute("INSERT INTO events(kind,data) VALUES('order_intent',?)",
                              (json.dumps({"ref": ref, "leg": leg, "volume": 1, "offset": offset, "price": price}),))
        self.can_open = False
        self.j.set("state", "OPENING" if leg == "OPEN" else "CLOSING")
        self.actions.append({"action": "send", **self.j.orders()[-1]})

    def order(self, ref, front, session, sysid, status, traded, instrument, volume):
        found = [o for o in self.j.orders() if o["ref"] == ref and o["front"] == front and o["session"] == session]
        if not found:
            return False
        o = found[0]
        if (instrument != self.plan.instrument or volume != 1 or traded not in (0, 1)
                or status not in self.TERMINAL | {"WORKING", "SUBMITTING"}
                or o["sysid"] and sysid and o["sysid"] != sysid):
            self.fault("INVALID_ORDER_REPORT")
            return False
        # Out-of-order working reports cannot resurrect a terminal order.
        new_status = status if o["status"] not in self.TERMINAL else o["status"]
        if status == "FILLED" or traded == 1:
            new_status = "FILLED"
        with self.j.db:
            self.j.db.execute("UPDATE orders SET sysid=?,status=?,reported=? WHERE ref=?",
                              (sysid or o["sysid"], new_status, max(traded, o["reported"]), ref))
        self.j.event("order_report", {"ref": ref, "status": new_status, "traded": traded})
        if status == "REJECTED" or status == "CANCELLED" and o["leg"] == "CLOSE":
            self.fault("ORDER_REJECTED_OR_CLOSE_CANCELLED")
        self.maybe_close()
        return True

    def trade(self, key, ref, volume, price, leg, instrument):
        o = next((o for o in self.j.orders() if o["ref"] == ref), None)
        if not o:
            return False
        previous = self.j.db.execute("SELECT * FROM fills WHERE key=?", (key,)).fetchone()
        if previous:
            if (previous["ref"], previous["volume"], previous["price"], previous["leg"]) != (ref, volume, price, leg):
                self.fault("CONFLICTING_DUPLICATE_FILL")
            return False
        if (leg != o["leg"] or instrument != self.plan.instrument or volume != 1
                or not math.isfinite(price) or price <= 0
                or self.j.db.execute("SELECT COUNT(*) FROM fills WHERE ref=?", (ref,)).fetchone()[0]):
            self.fault("INVALID_FILL")
            return False
        if leg == "CLOSE" and self.j.totals()["OPEN"] != 1:
            self.fault("CLOSE_BEFORE_OPEN")
            return False
        with self.j.db:
            self.j.db.execute("INSERT INTO fills VALUES(?,?,?,?,?)", (key, ref, volume, price, leg))
            self.j.db.execute("INSERT OR REPLACE INTO meta VALUES('last_fill_time',?)", (json.dumps(self.clock()),))
            self.j.db.execute("INSERT INTO events(kind,data) VALUES('fill',?)",
                              (json.dumps({"ref": ref, "leg": leg, "volume": volume, "price": price}),))
        self.maybe_close()
        return True

    def maybe_close(self):
        if not self.connected or not self.reconciled or self.j.totals() != {"OPEN": 1, "CLOSE": 0}:
            return
        orders = self.j.orders()
        if any(o["status"] not in self.TERMINAL for o in orders):
            return
        if any(o["reported"] != self.j.db.execute("SELECT COALESCE(SUM(volume),0) FROM fills WHERE ref=?", (o["ref"],)).fetchone()[0] for o in orders):
            return
        # After a failed close, only a new full reconciliation can enable another.
        offset = "CLOSE_TODAY" if self.plan.exchange in {"SHFE", "INE"} else "CLOSE"
        if self.quote:
            self.submit("CLOSE", self.quote.bid, offset)

    def timeouts(self):
        now = self.clock()
        for o in self.j.orders():
            if o["status"] in self.TERMINAL:
                continue
            if o["cancel_sent"] is not None and now-o["cancel_sent"] >= self.plan.cancel_timeout:
                self.fault("CANCEL_STATE_UNKNOWN")
            elif o["cancel_sent"] is None and now-o["sent"] >= self.plan.order_timeout:
                self.fault("ORDER_TIMEOUT")

    def take_actions(self):
        actions, self.actions = self.actions, []
        return actions

    def evidence(self):
        rows = [dict(x) for x in self.j.db.execute("SELECT seq,kind,data FROM events ORDER BY seq")]
        for r in rows:
            r["data"] = json.loads(r["data"])
        return {"schema_version": 1, "mode": self.plan.mode, "plan": asdict(self.plan),
                "plan_hash": self.j.get("plan_hash"), "status": self.j.get("state"),
                "live_acceptance": "PASS" if self.plan.mode == "SIMNOW" and self.j.get("state") == "PASS" else "NOT_PASSED",
                "fills": self.j.totals(), "events": rows}
