#!/usr/bin/env python3
"""ci_check.py — 2. lépés: belépés felhőből, kizárólag a mentett tokennel.
A tokent SOHA nem írja ki, csak azt, hogy működik-e és változott-e."""
import base64, hashlib, json, os, sys
from datetime import date, datetime, timedelta, timezone
from garminconnect import Garmin

raw = os.environ.get("GARMINTOKENS")
if not raw:
    sys.exit("✗ GARMINTOKENS secret hiányzik")

h = lambda s: hashlib.sha256((s or "").encode()).hexdigest()[:8]
before = h(json.loads(raw).get("di_refresh_token"))

g = Garmin()
g.login(raw)                       # csak token, jelszó nincs a felhőben
print("✓ Belépés tokennel sikeres")

today = date.today()
acts = g.get_activities_by_date((today - timedelta(days=3)).isoformat(), today.isoformat())
print(f"✓ Aktivitások (utolsó 3 nap): {len(acts)} db")
sl = (g.get_sleep_data(today.isoformat()) or {}).get("dailySleepDTO") or {}
print(f"✓ Mai alvásadat: {'van' if sl.get('sleepTimeSeconds') else 'nincs'}")

c = g.client
after = h(c.di_refresh_token)
print(f"Refresh token változott: {'IGEN — a Secretet frissíteni kell' if before != after else 'nem'}")
try:
    p = c.di_token.split(".")[1]; p += "=" * (-len(p) % 4)
    exp = datetime.fromtimestamp(json.loads(base64.urlsafe_b64decode(p))["exp"], timezone.utc)
    print(f"Access token lejár: {exp:%Y-%m-%d %H:%M} UTC")
except Exception:
    print("Access token lejárata nem olvasható")
