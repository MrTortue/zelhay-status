#!/usr/bin/env python3
"""Sonde externe : lit targets.yml, teste chaque cible, met à jour data/.

Sorties :
  data/history/<id>.json   échantillons horodatés (ts, ok, ms, err) sur `history_days`
  data/summary.json        état courant + uptime 24h/7j/30j/90j par cible
  data/incidents.json      incidents ouverts/fermés (avec n° d'Issue GitHub)
"""
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HIST = DATA / "history"
WINDOWS = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


# --------------------------------------------------------------------------- sondes
def _tcp(host, port, timeout):
    t0 = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout) as s:
        return s, (time.perf_counter() - t0) * 1000


def check_tcp(t, timeout, any_port=False):
    errs = []
    best = None
    for port in t["ports"]:
        try:
            s, ms = _tcp(t["host"], port, timeout)
            s.close()
            best = ms if best is None else min(best, ms)
            if any_port:
                return True, ms, None
        except OSError as e:
            errs.append(f"{port}: {e}")
            if not any_port:
                return False, None, "; ".join(errs)
    if any_port:
        return False, None, "; ".join(errs)
    return True, best, None


def check_http(t, timeout):
    url = t["url"]
    expect = t.get("expect", [200, 399])
    lo, hi = (expect, expect) if isinstance(expect, int) else expect
    req = urllib.request.Request(url, headers={"User-Agent": "zelhay-status-probe/1.0"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    ms = (time.perf_counter() - t0) * 1000
    extra = {}
    if url.startswith("https://"):
        extra["tls_days_left"] = tls_days_left(urllib.parse.urlparse(url).hostname, timeout)
    ok = lo <= code <= hi
    err = None if ok else f"HTTP {code}" + (" (bloqué par un pare-feu applicatif ?)" if code == 403 else "")
    return ok, ms, err, extra


def tls_days_left(host, timeout):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as s, ctx.wrap_socket(s, server_hostname=host) as ss:
            exp = ss.getpeercert()["notAfter"]
        exp_dt = datetime.strptime(exp, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return (exp_dt - datetime.now(timezone.utc)).days
    except Exception:
        return None


def check_banner(t, timeout, use_tls, expect):
    s, ms = _tcp(t["host"], t["port"], timeout)
    try:
        if use_tls:
            s = ssl.create_default_context().wrap_socket(s, server_hostname=t["host"])
        s.settimeout(timeout)
        banner = s.recv(256).decode(errors="replace")
    finally:
        s.close()
    ok = banner.startswith(expect)
    return ok, ms, (None if ok else f"bannière inattendue: {banner[:60]!r}")


def check_ping(t, timeout):
    t0 = time.perf_counter()
    r = subprocess.run(["ping", "-c", "1", "-W", str(int(timeout)), t["host"]], capture_output=True, text=True)
    ms = (time.perf_counter() - t0) * 1000
    return r.returncode == 0, ms, (None if r.returncode == 0 else "ICMP sans réponse")


def run_check(t, timeout):
    kind = t["type"]
    try:
        if kind == "http":
            return check_http(t, timeout)
        if kind == "tcp":
            return (*check_tcp(t, timeout), {})
        if kind == "tcp_any":
            return (*check_tcp(t, timeout, any_port=True), {})
        if kind == "ping":
            return (*check_ping(t, timeout), {})
        if kind == "smtp":
            return (*check_banner(t, timeout, False, "220"), {})
        if kind == "imap":
            return (*check_banner(t, timeout, True, "* OK"), {})
        return False, None, f"type inconnu: {kind}", {}
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}", {}


def probe(t, settings):
    timeout = settings["timeout_seconds"]
    # Ré-essais espacés : un blocage ponctuel (pare-feu applicatif, rate-limit,
    # saturation passagère) ne doit pas compter comme une indisponibilité.
    delays = settings.get("retry_delays", [3, 10])
    result = None
    for i in range(1 + len(delays)):
        result = run_check(t, timeout)
        if result[0]:
            break
        if i < len(delays):
            time.sleep(delays[i])
    via = t["type"]
    if not result[0] and t.get("fallback"):
        fb = {**t, **t["fallback"]}
        fb_res = run_check(fb, timeout)
        if fb_res[0]:
            result, via = fb_res, f"{t['type']}→{fb['type']}"
    ok, ms, err, extra = result
    return {"ts": int(time.time()), "ok": bool(ok), "ms": round(ms) if ms is not None else None,
            "err": err, "via": via, **extra}


# --------------------------------------------------------------------------- historique / uptime
def load_json(p, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def uptime(samples, days, now):
    since = now - days * 86400
    win = [s for s in samples if s["ts"] >= since]
    if not win:
        return None
    return round(100 * sum(1 for s in win if s["ok"]) / len(win), 3)


def streak_failures(samples):
    n = 0
    for s in reversed(samples):
        if s["ok"]:
            break
        n += 1
    return n


# --------------------------------------------------------------------------- incidents / issues GitHub
def gh_api(method, path, body=None):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or "{}")
    except Exception as e:  # noqa: BLE001
        print(f"[gh] {method} {path} échec: {e}", file=sys.stderr)
        return None


def update_incidents(incidents, target, sample, confirmed_down, now_iso, settings):
    open_inc = next((i for i in incidents if i["target"] == target["id"] and not i["resolved_at"]), None)
    if confirmed_down and not open_inc:
        inc = {"target": target["id"], "name": target["name"], "started_at": now_iso, "resolved_at": None,
               "error": sample["err"], "issue": None}
        if settings.get("open_github_issues"):
            r = gh_api("POST", "/issues", {"title": f"🔴 Panne : {target['name']}",
                                           "labels": ["incident", "status"],
                                           "body": f"Cible `{target['id']}` injoignable depuis {now_iso}.\n\nErreur : `{sample['err']}`\n\n"
                                                   f"Détectée par la sonde externe (GitHub Actions). Cette issue sera fermée automatiquement au retour du service."})
            inc["issue"] = r.get("number") if r else None
        incidents.append(inc)
        print(f"[incident] ouvert : {target['name']}")
    elif sample["ok"] and open_inc:
        open_inc["resolved_at"] = now_iso
        if open_inc.get("issue") and settings.get("open_github_issues"):
            dur = datetime.fromisoformat(now_iso) - datetime.fromisoformat(open_inc["started_at"])
            gh_api("POST", f"/issues/{open_inc['issue']}/comments", {"body": f"✅ Service rétabli à {now_iso} (durée : {dur})."})
            gh_api("PATCH", f"/issues/{open_inc['issue']}", {"state": "closed"})
        print(f"[incident] résolu : {target['name']}")


# --------------------------------------------------------------------------- main
def main():
    cfg = yaml.safe_load((ROOT / "targets.yml").read_text())
    settings = cfg["settings"]
    HIST.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    keep_since = now - settings["history_days"] * 86400

    targets = [(g["name"], t) for g in cfg["groups"] for t in g["targets"]]
    with ThreadPoolExecutor(max_workers=12) as ex:
        samples = list(ex.map(lambda gt: probe(gt[1], settings), targets))

    incidents = load_json(DATA / "incidents.json", [])
    summary = {"generated_at": now_iso, "sla_target": settings["sla_target"],
               "confirm_failures": settings["confirm_failures"], "groups": []}
    by_group = {}
    for (gname, t), s in zip(targets, samples):
        hp = HIST / f"{t['id']}.json"
        hist = [x for x in load_json(hp, []) if x["ts"] >= keep_since]
        hist.append(s)
        hp.write_text(json.dumps(hist, separators=(",", ":")))

        fails = streak_failures(hist)
        confirmed_down = fails >= settings["confirm_failures"]
        update_incidents(incidents, t, s, confirmed_down, now_iso, settings)

        status = "down" if confirmed_down else ("degraded" if not s["ok"] else "up")
        entry = {"id": t["id"], "name": t["name"], "type": t["type"], "status": status, "last": s,
                 "uptime": {k: uptime(hist, d, now) for k, d in WINDOWS.items()},
                 "avg_ms_24h": None}
        recent = [x["ms"] for x in hist if x["ts"] >= now - 86400 and x["ms"] is not None]
        if recent:
            entry["avg_ms_24h"] = round(sum(recent) / len(recent))
        by_group.setdefault(gname, []).append(entry)
        flag = "OK " if s["ok"] else "KO "
        print(f"{flag} {t['name']:<28} {s['ms'] or '-':>6} ms  via {s['via']}  {s['err'] or ''}")

    for gname, entries in by_group.items():
        summary["groups"].append({"name": gname, "targets": entries})
    all_t = [e for g in summary["groups"] for e in g["targets"]]
    summary["overall"] = "down" if any(e["status"] == "down" for e in all_t) else (
        "degraded" if any(e["status"] == "degraded" for e in all_t) else "up")
    summary["global_uptime"] = {k: (round(sum(v for v in vals) / len(vals), 3) if (vals := [e["uptime"][k] for e in all_t if e["uptime"][k] is not None]) else None)
                                for k in WINDOWS}
    (DATA / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    (DATA / "incidents.json").write_text(json.dumps(incidents, indent=1, ensure_ascii=False))
    print(f"\nGlobal : {summary['overall']}  uptime 30j = {summary['global_uptime']['30d']}%")


if __name__ == "__main__":
    main()
