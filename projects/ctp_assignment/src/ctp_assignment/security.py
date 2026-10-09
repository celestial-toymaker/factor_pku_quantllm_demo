"""Private configuration and narrow public evidence projection."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
from .core import StopRun

# Observed directly on the official product page on 2026-10-09. Pairing matters.
SIMNOW_PAIRS = {
    (f"tcp://182.254.243.31:{td}", f"tcp://182.254.243.31:{md}")
    for td, md in ((30001, 30011), (30002, 30012), (30003, 30013), (40001, 40011))
}


def load_private(path):
    path = Path(path).resolve()
    if path.stat().st_mode & 0o077:
        raise StopRun("PRIVATE_CONFIG_PERMISSIONS_MUST_BE_600")
    repo = Path(__file__).resolve().parents[4]
    if path.is_relative_to(repo):
        raise StopRun("PRIVATE_CONFIG_MUST_BE_OUTSIDE_REPOSITORY")
    try:
        cfg = json.loads(path.read_text())
    except (ValueError, OSError):
        raise StopRun("INVALID_PRIVATE_CONFIG") from None
    fields = ("user_id", "password", "broker_id", "app_id", "auth_code", "td_front", "md_front")
    if any(not isinstance(cfg.get(k), str) or not cfg[k] for k in fields):
        raise StopRun("PRIVATE_CONFIG_INCOMPLETE")
    # The upstream binding copies into fixed-size CTP character arrays.
    for key, limit in (("user_id",15),("broker_id",10),("password",40),("app_id",32),("auth_code",16)):
        if len(cfg[key].encode("utf-8")) > limit or "\x00" in cfg[key]:
            raise StopRun("PRIVATE_FIELD_EXCEEDS_CTP_LIMIT")
    if cfg["broker_id"] != "9999" or (cfg["td_front"], cfg["md_front"]) not in SIMNOW_PAIRS:
        raise StopRun("ONLY_VERIFIED_SIMNOW_ENDPOINTS_ALLOWED")
    try:
        verified = date.fromisoformat(cfg["endpoints_verified_on"])
    except (KeyError, ValueError):
        raise StopRun("ENDPOINT_VERIFICATION_REQUIRED") from None
    if not 0 <= (date.today()-verified).days <= 7:
        raise StopRun("ENDPOINT_VERIFICATION_EXPIRED")
    return cfg


def binding(cfg):
    # Private journal only. Never exported, even as a hash of a small account ID.
    return hashlib.sha256((cfg["broker_id"]+":"+cfg["user_id"]).encode()).hexdigest()


def redact(text, cfg):
    for k in ("password", "auth_code", "user_id"):
        if cfg.get(k):
            text = text.replace(cfg[k], "[REDACTED]")
    return text


def write_public(path, obj, cfg=None):
    text = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
    if cfg and redact(text, cfg) != text:
        raise StopRun("SECRET_IN_EXPORT")
    if re.search(r'"(?:UserID|Password|AuthCode|AccountID|Available|Balance)"\s*:', text, re.I):
        raise StopRun("PRIVATE_FIELD_IN_EXPORT")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(text)
    os.replace(temp, path)


def verify_evidence(e):
    if e.get("schema_version") != 1 or e.get("mode") not in {"DRY_RUN", "SIMNOW"}:
        raise StopRun("INVALID_EVIDENCE")
    digest = hashlib.sha256(json.dumps(e["plan"], sort_keys=True).encode()).hexdigest()
    if digest != e.get("plan_hash"):
        raise StopRun("EVIDENCE_PLAN_HASH_MISMATCH")
    events = e["events"]
    if [x["seq"] for x in events] != list(range(1, len(events)+1)):
        raise StopRun("EVIDENCE_SEQUENCE_GAP")
    orders = [x["data"] for x in events if x["kind"] == "order_intent"]
    if sum(x["leg"] == "OPEN" for x in orders) > 1 or any(x["volume"] != 1 for x in orders):
        raise StopRun("EVIDENCE_EXPOSURE_LIMIT")
    fills = [x for x in events if x["kind"] == "fill"]
    totals = {leg: sum(x["data"]["volume"] for x in fills if x["data"]["leg"] == leg) for leg in ("OPEN", "CLOSE")}
    if totals != e["fills"] or not 0 <= totals["CLOSE"] <= totals["OPEN"] <= 1:
        raise StopRun("EVIDENCE_FILL_MISMATCH")
    if e["status"] in {"PASS", "OFFLINE_PASS"}:
        if totals != {"OPEN": 1, "CLOSE": 1}:
            raise StopRun("ACCEPTANCE_REQUIRES_BOTH_FILLS")
        last = events[-1]
        if last["kind"] != "reconciled" or last["seq"] <= fills[-1]["seq"]:
            raise StopRun("ACCEPTANCE_REQUIRES_FINAL_QUERIES")
        d = last["data"]
        if (set(d["completed"]) != {"orders", "trades", "positions"} or not d["stable"]
                or (d["long"], d["short"], d["active_orders"]) != (0, 0, 0)):
            raise StopRun("ACCEPTANCE_NOT_FLAT")
        expected = "PASS" if e["mode"] == "SIMNOW" else "OFFLINE_PASS"
        if e["status"] != expected:
            raise StopRun("SIMULATION_CANNOT_PROVE_LIVE_ACCEPTANCE")
    if e.get("live_acceptance") == "PASS" and (e["mode"], e["status"]) != ("SIMNOW", "PASS"):
        raise StopRun("SIMULATION_CANNOT_PROVE_LIVE_ACCEPTANCE")
    return {"valid": True, "mode": e["mode"], "status": e["status"], "live_acceptance": e["live_acceptance"]}
