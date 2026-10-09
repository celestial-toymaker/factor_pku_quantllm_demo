"""Thin low-level adapter. Importing this module makes no network connection."""
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import queue
import sys
import time
from zoneinfo import ZoneInfo
from .core import Quote, StopRun


def load_native(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory.parent / "build_manifest.json").read_text())
    for name, digest in manifest["outputs"].items():
        f = (directory / name).resolve()
        if not f.is_relative_to(directory) or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            raise StopRun("NATIVE_BUILD_FINGERPRINT_MISMATCH")
    modules = []
    for name in ("vnctpmd", "vnctptd"):
        matches = list(directory.glob(name+"*.so"))
        if len(matches) != 1:
            raise StopRun("NATIVE_EXTENSION_MISSING")
        spec = importlib.util.spec_from_file_location(name, matches[0])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        modules.append(mod)
    return modules


class Native:
    def __init__(self, directory, cfg, flow_dir):
        mdmod, tdmod = load_native(directory)
        self.cfg = cfg
        self.flow = Path(flow_dir)
        self.q = queue.Queue()
        self.pending = []
        self.reqid = 0
        self.last_query = 0.0
        self.latest = {}
        self.initialized = []
        self.session = {}
        self.contracts = {}
        self.market_status = {}
        self.subscription_count = 0
        self.phase = "CREATED"
        self.trace = []
        owner = self

        def callback(side, name):
            def cb(_self, *args):
                # Native callbacks only enqueue. State and sqlite live on one thread.
                owner.q.put((side, name, args, time.monotonic()))
            return cb

        shared = ["onFrontConnected", "onFrontDisconnected", "onHeartBeatWarning", "onRspError", "onRspUserLogin"]
        td_names = shared + ["onRspAuthenticate", "onRspSettlementInfoConfirm", "onRspQryInstrument",
                            "onRspQryOrder", "onRspQryTrade", "onRspQryInvestorPosition",
                            "onRspQryTradingAccount", "onRspQryInstrumentMarginRate",
                            "onRspQryInstrumentCommissionRate", "onRtnOrder", "onRtnTrade",
                            "onRspOrderInsert", "onErrRtnOrderInsert", "onRspOrderAction", "onErrRtnOrderAction",
                            "onRtnInstrumentStatus"]
        md_names = shared + ["onRspSubMarketData", "onRtnDepthMarketData"]
        self.md = type("AssignmentMd", (mdmod.MdApi,), {n: callback("MD", n) for n in md_names})()
        self.td = type("AssignmentTd", (tdmod.TdApi,), {n: callback("TD", n) for n in td_names})()

    def _event(self, timeout):
        try:
            e = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        side, name, args, received = e
        item = {"api": side, "event": name}
        if len(args) == 4:
            item.update(request_id=args[2], last=args[3], error_code=args[1].get("ErrorID", 0))
        if self.trace and {k:v for k,v in self.trace[-1].items() if k != "count"} == item:
            self.trace[-1]["count"] += 1
        else:
            self.trace.append({**item, "count": 1})
        self.trace = self.trace[-200:]
        if name in {"onFrontDisconnected", "onHeartBeatWarning"}:
            raise StopRun("CONNECTION_OR_HEARTBEAT_LOST")
        if name == "onRspError":
            raise StopRun("CTP_RESPONSE_ERROR")
        if name == "onRtnDepthMarketData":
            self.latest[args[0].get("InstrumentID")] = (args[0], received)
        elif name == "onRtnInstrumentStatus":
            d = args[0]
            self.market_status[(d.get("ExchangeID"), d.get("InstrumentID"))] = d.get("InstrumentStatus")
        elif name == "onRspSubMarketData":
            if args[1].get("ErrorID", 0):
                raise StopRun("SUBSCRIPTION_REJECTED")
            self.subscription_count += 1
        return e

    def wait(self, side, name, reqid=None, timeout=15):
        end = time.monotonic()+timeout
        rows = []
        while time.monotonic() < end:
            e = self._event(min(0.25, max(0.001, end-time.monotonic())))
            if e is None:
                continue
            s, n, args, _ = e
            # Observed SimNow MD login returns request id 0. Only this handshake
            # on a newly constructed MD connection accepts zero; TD and every
            # reconciliation query retain exact request-id and bIsLast checks.
            md_login_zero = side == "MD" and name == "onRspUserLogin" and len(args) == 4 and args[2] == 0
            if (s, n) == (side, name) and (reqid is None or len(args) == 4 and args[2] == reqid or md_login_zero):
                if not args:
                    return []
                data, err, _, last = args
                if err.get("ErrorID", 0):
                    # Error codes are useful; server messages may echo private fields.
                    raise StopRun("CTP_REQUEST_REJECTED_CODE_"+str(int(err["ErrorID"])))
                if data:
                    rows.append(data)
                if last:
                    return rows
            elif n not in {"onRtnDepthMarketData", "onRspSubMarketData"}:
                self.pending.append(e)
        raise StopRun("CTP_REQUEST_TIMEOUT")

    def request(self, method, response, fields, query=False, api=None, side="TD"):
        self.phase = side+"_"+method
        if query:
            # Respect per-session CTP query throttling, including empty results.
            delay = 1.1-(time.monotonic()-self.last_query)
            if delay > 0:
                time.sleep(delay)
            self.last_query = time.monotonic()
        self.reqid += 1
        api = api or self.td
        result = getattr(api, method)(fields, self.reqid)
        if result != 0:
            raise StopRun("CTP_REQUEST_NOT_ACCEPTED_"+str(result))
        return self.wait(side, response, self.reqid)

    def connect(self, trading=True):
        c = self.cfg
        for side, api, front in (("MD", self.md, c["md_front"]), ("TD", self.td, c["td_front"])):
            if side == "TD" and not trading:
                continue
            flow = self.flow / side
            flow.mkdir(parents=True, mode=0o700, exist_ok=True)
            # SimNow's published fronts use production monitoring keys. This flag
            # selects SDK cryptography; the endpoint allowlist selects simulation.
            getattr(api, "createFtdcMdApi" if side == "MD" else "createFtdcTraderApi")(str(flow)+"/", True)
            if side == "TD":
                api.subscribePrivateTopic(0)
                api.subscribePublicTopic(0)
            api.registerFront(front)
            self.phase = side+"_CONNECT"
            api.init()
            self.initialized.append(api)
            self.wait(side, "onFrontConnected")
            if side == "TD":
                self.request("reqAuthenticate", "onRspAuthenticate", {
                    "BrokerID": c["broker_id"], "UserID": c["user_id"],
                    "AuthCode": c["auth_code"], "AppID": c["app_id"]})
            rows = self.request("reqUserLogin", "onRspUserLogin", {
                "BrokerID": c["broker_id"], "UserID": c["user_id"], "Password": c["password"]}, api=api, side=side)
            if side == "TD":
                if len(rows) != 1:
                    raise StopRun("LOGIN_SESSION_MISSING")
                self.session = rows[0]
                self.request("reqSettlementInfoConfirm", "onRspSettlementInfoConfirm", self.identity())

    def identity(self):
        return {"BrokerID": self.cfg["broker_id"], "InvestorID": self.cfg["user_id"]}

    def query(self, kind, instrument=""):
        mapping = {
            "orders": ("reqQryOrder", "onRspQryOrder"),
            "trades": ("reqQryTrade", "onRspQryTrade"),
            "positions": ("reqQryInvestorPosition", "onRspQryInvestorPosition"),
            "account": ("reqQryTradingAccount", "onRspQryTradingAccount"),
            "instrument": ("reqQryInstrument", "onRspQryInstrument"),
            "margin": ("reqQryInstrumentMarginRate", "onRspQryInstrumentMarginRate"),
            "commission": ("reqQryInstrumentCommissionRate", "onRspQryInstrumentCommissionRate"),
        }
        fields = self.identity()
        if instrument:
            fields["InstrumentID"] = instrument
        if kind == "margin":
            fields["HedgeFlag"] = "1"
        return self.request(*mapping[kind], fields, query=True)

    def subscribe(self, instruments):
        for instrument in instruments:
            if self.md.subscribeMarketData(instrument) != 0:
                raise StopRun("SUBSCRIPTION_NOT_ACCEPTED")

    def drain(self, seconds=0.1):
        events, self.pending = self.pending, []
        end = time.monotonic()+seconds
        while time.monotonic() < end or not self.q.empty():
            e = self._event(max(0, min(0.1, end-time.monotonic())))
            if e and e[1] not in {"onRtnDepthMarketData", "onRspSubMarketData"}:
                events.append(e)
            if e is None and time.monotonic() >= end:
                break
        return events

    def quote(self, instrument):
        if instrument not in self.latest or instrument not in self.contracts:
            return None
        d, received = self.latest[instrument]
        try:
            stamp = datetime.strptime(str(d["ActionDay"])+" "+d["UpdateTime"], "%Y%m%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            stamp = stamp.timestamp()+d.get("UpdateMillisec", 0)/1000
            age = time.time()-stamp
            return Quote(instrument, d["LastPrice"], d["BidPrice1"], d["AskPrice1"],
                         d["LowerLimitPrice"], d["UpperLimitPrice"], received, age, self.contracts[instrument]["PriceTick"])
        except (KeyError, ValueError, TypeError):
            return None

    def market_open(self, instrument):
        d = self.contracts.get(instrument, {})
        exchange = d.get("ExchangeID")
        status = self.market_status.get((exchange, instrument),
                                       self.market_status.get((exchange, d.get("ProductID"))))
        # CTP THOST_FTDC_IS_Continous = '2'. Unknown status cannot arm a run.
        return status == "2"

    def send(self, action, plan):
        self.reqid += 1
        fields = {**self.identity(), "UserID": self.cfg["user_id"], "InstrumentID": plan.instrument,
                  "ExchangeID": plan.exchange, "OrderRef": action["ref"], "Direction": "0" if action["leg"] == "OPEN" else "1",
                  "CombOffsetFlag": {"OPEN": "0", "CLOSE": "1", "CLOSE_TODAY": "3"}[action["offset"]],
                  "CombHedgeFlag": "1", "LimitPrice": action["price"], "VolumeTotalOriginal": 1,
                  "OrderPriceType": "2", "TimeCondition": "3", "VolumeCondition": "1", "MinVolume": 1,
                  "ContingentCondition": "1", "ForceCloseReason": "0", "IsAutoSuspend": 0}
        if self.td.reqOrderInsert(fields, self.reqid) != 0:
            raise StopRun("ORDER_SEND_RESULT_UNKNOWN")

    def cancel(self, action, plan):
        self.reqid += 1
        fields = {**self.identity(), "InstrumentID": plan.instrument, "ExchangeID": plan.exchange,
                  "OrderRef": action["ref"], "FrontID": action["front"], "SessionID": action["session"],
                  "ActionFlag": "0"}
        if action["sysid"]:
            fields["OrderSysID"] = action["sysid"]
        if self.td.reqOrderAction(fields, self.reqid) != 0:
            raise StopRun("CANCEL_SEND_RESULT_UNKNOWN")

    def close(self):
        failures = []
        for api in reversed(self.initialized):
            try:
                api.exit()
            except Exception:
                failures.append(True)
        self.initialized = []
        if failures:
            raise StopRun("NATIVE_SHUTDOWN_INCOMPLETE")
