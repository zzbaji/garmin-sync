#!/usr/bin/env python3
"""garmin_sync.py — GitHub Actionsben fut.

1. Belép a Garminba (először a repóban titkosítva tárolt, frissített tokennel,
   ennek hiányában a GARMINTOKENS secrettel).
2. Lekéri az utolsó WINDOW_DAYS nap aktivitásait; az új tekeréseket letölti
   (ORIGINAL .fit), elemzi, és titkosítva archiválja.
3. Lekéri az alvásokat (a hiányzó napokat + az utolsó SLEEP_REFRESH_DAYS napot újra,
   mert a Garmin utólag újraszámol).
4. Megírja a titkosított indexet (data/index.enc), amit Claude a chatből olvas.
"""
import io, json, os, sys, time, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from garminconnect import Garmin
from analyze import analyze, VERSION as AN_VER
from feedcrypt import decrypt, opaque_name, write_if_changed

WINDOW_DAYS = 45
SLEEP_REFRESH_DAYS = 3
ROOT = Path(__file__).parent
DATA, ARCH, STATE = ROOT / "data", ROOT / "archive", ROOT / "state"

FEED_KEY = os.environ["FEED_KEY"]               # Claude is ismeri: feed visszafejtése
TOKEN_KEY = os.environ.get("TOKEN_KEY")          # csak az Actions ismeri: Garmin-token
TOKEN_FILE = STATE / "t.enc"

RIDE_TYPES = {"cycling", "mountain_biking", "road_biking", "gravel_cycling",
              "cyclocross", "virtual_ride", "indoor_cycling", "e_bike_mountain"}
INDOOR = {"virtual_ride", "indoor_cycling"}
NAPOK = ["H", "K", "Sze", "Cs", "P", "Szo", "V"]


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- belépés
def connect():
    tok, src = None, None
    if TOKEN_KEY and TOKEN_FILE.exists():
        try:
            tok, src = decrypt(TOKEN_KEY, TOKEN_FILE.read_bytes()).decode(), "repó"
        except Exception as e:
            log(f"! A tárolt token nem fejthető vissza ({e}), secret következik")
    if not tok:
        tok, src = os.environ["GARMINTOKENS"], "secret"
    g = Garmin()
    g.login(tok)
    log(f"✓ Belépés ({src} token)")
    return g, tok


def save_token(g, old):
    new = g.client.dumps()
    if json.loads(new).get("di_refresh_token") != json.loads(old).get("di_refresh_token") \
            or json.loads(new).get("di_token") != json.loads(old).get("di_token"):
        if TOKEN_KEY:
            write_if_changed(TOKEN_KEY, TOKEN_FILE, new.encode())
            log("✓ Garmin-token frissült, titkosítva elmentve")
        else:
            log("! A token frissült, de nincs TOKEN_KEY — a következő futás elbukhat")


# ---------------------------------------------------------------- besorolás
def categorize(a):
    typ = (a.get("activityType") or {}).get("typeKey", "")
    km = (a.get("distance") or 0) / 1000
    dur = a.get("duration") or 0
    hour = int(str(a.get("startTimeLocal", "00:00:00 00"))[11:13] or 0)
    up, down = a.get("elevationGain") or 0, a.get("elevationLoss") or 0
    if typ == "strength_training":
        return "kondi"
    if typ in INDOOR:
        return "gorgo"
    if typ in RIDE_TYPES:
        if 14 <= km <= 18.5:
            if hour < 12 and down > up:
                return "odaut"
            if hour >= 12 and up > down:
                return "hazaut"
        if dur >= 90 * 60:
            return "hosszu"
        return "egyeb_tekeres"
    return "egyeb"


def fetch_fit(g, aid):
    data = g.download_activity(str(aid), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.lower().endswith(".fit"):
                return z.read(n)
    raise RuntimeError("nincs .fit a zipben")


# ---------------------------------------------------------------- alvás
def hm(sec):
    if sec is None:
        return None
    m = int(round(sec / 60))
    return f"{m // 60}:{m % 60:02d}"


def sleep_summary(s):
    d = s.get("dailySleepDTO") or {}
    if not d.get("sleepTimeSeconds"):
        return None
    loc = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%H:%M") if ms else None
    stress = [x["value"] for x in s.get("sleepStress") or [] if (x.get("value") or -1) >= 0]
    bb = [x["value"] for x in s.get("sleepBodyBattery") or [] if x.get("value") is not None]
    bbc = s.get("bodyBatteryChange")
    return {
        "alvas": hm(d.get("sleepTimeSeconds")), "mely": hm(d.get("deepSleepSeconds")),
        "konnyu": hm(d.get("lightSleepSeconds")), "REM": hm(d.get("remSleepSeconds")),
        "ebren": hm(d.get("awakeSleepSeconds")),
        "nyug_HR": s.get("restingHeartRate"),
        "BB": (f"+{bbc}" if bbc and bbc > 0 else str(bbc)) if bbc is not None else None,
        "BB_ebredeskor": bb[-1] if bb else None,
        "elalvas": loc(d.get("sleepStartTimestampLocal")),
        "ebredes": loc(d.get("sleepEndTimestampLocal")),
        "legzes_atl": d.get("averageRespirationValue"),
        "stressz_atl": round(sum(stress) / len(stress)) if stress else None,
    }


# ---------------------------------------------------------------- fő
def main():
    g, tok = connect()
    today = date.today()
    start = today - timedelta(days=WINDOW_DAYS - 1)

    idx_path = DATA / "index.enc"
    old = {}
    if idx_path.exists():
        try:
            old = json.loads(decrypt(FEED_KEY, idx_path.read_bytes()))
        except Exception as e:
            log(f"! Régi index nem olvasható ({e}), újraépítés")
    old_acts = {a["id"]: a for a in old.get("aktivitasok", [])}
    sleeps = {d: v for d, v in old.get("alvas", {}).items() if d >= start.isoformat()}

    # --- aktivitások
    acts = g.get_activities_by_date(start.isoformat(), today.isoformat(), sortorder="asc")
    out_acts, new_cnt = [], 0
    for a in acts:
        aid = a["activityId"]
        cat = categorize(a)
        st = str(a.get("startTimeLocal", ""))
        entry = {
            "id": aid, "datum": st[:10], "nap": NAPOK[date.fromisoformat(st[:10]).weekday()],
            "kezdes": st[11:16], "garmin_tipus": (a.get("activityType") or {}).get("typeKey"),
            "nev": a.get("activityName"), "km": round((a.get("distance") or 0) / 1000, 2),
            "ido": hm(a.get("duration")), "kategoria": cat, "elemzes": None,
        }
        prev = old_acts.get(aid)
        if cat in ("kondi", "egyeb"):
            pass                                    # kondi: elég a bejegyzés, nincs letöltés
        elif prev and prev.get("elemzes") and prev.get("v") == AN_VER:
            entry["elemzes"], entry["v"] = prev["elemzes"], AN_VER
        else:
            try:
                name = opaque_name(FEED_KEY, f"act:{aid}")
                arch = ARCH / "fit" / f"{name}.enc"
                if arch.exists():                       # újraelemzés az archívumból
                    fit = decrypt(FEED_KEY, arch.read_bytes())
                else:
                    fit = fetch_fit(g, aid)
                    write_if_changed(FEED_KEY, arch, fit)
                    time.sleep(1)
                res = analyze(fit, cat)
                res["garmin_id"] = aid
                write_if_changed(FEED_KEY, DATA / "a" / f"{name}.enc",
                                 json.dumps(res, ensure_ascii=False, default=str).encode())
                entry["elemzes"], entry["v"] = name, AN_VER
                new_cnt += 1
            except Exception as e:
                log(f"! {aid} ({entry['datum']} {entry['kezdes']}) letöltése/elemzése sikertelen: {e}")
        out_acts.append(entry)
    log(f"✓ Aktivitások: {len(out_acts)} db, ebből (új)elemzés: {new_cnt}")

    # --- alvás
    refresh_from = today - timedelta(days=SLEEP_REFRESH_DAYS - 1)
    d, fetched = start, 0
    while d <= today:
        ds = d.isoformat()
        if ds not in sleeps or d >= refresh_from:
            try:
                raw = g.get_sleep_data(ds) or {}
                summ = sleep_summary(raw)
                if summ:
                    sleeps[ds] = summ
                    write_if_changed(FEED_KEY, ARCH / "sleep" / f"{opaque_name(FEED_KEY, 'sleep:' + ds)}.enc",
                                     json.dumps(raw, ensure_ascii=False).encode())
                fetched += 1
                time.sleep(0.5)
            except Exception as e:
                log(f"! Alvás {ds}: {e}")
        d += timedelta(days=1)
    log(f"✓ Alvás: {len(sleeps)} nap ismert, most lekérve: {fetched}")

    index = {"ablak": [start.isoformat(), today.isoformat()],
             "aktivitasok": out_acts, "alvas": dict(sorted(sleeps.items()))}
    # a generálás idejét nem tesszük az indexbe, hogy változatlan adatnál ne legyen commit
    changed = write_if_changed(FEED_KEY, idx_path,
                               json.dumps(index, ensure_ascii=False, sort_keys=True).encode())
    log(f"✓ Index {'frissítve' if changed else 'változatlan'}")
    save_token(g, tok)


if __name__ == "__main__":
    main()
