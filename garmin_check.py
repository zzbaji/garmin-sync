#!/usr/bin/env python3
"""
garmin_check.py — 1. lépés: Garmin-kapcsolat ellenőrzése

Mit csinál:
  1. Belép a Garmin Connectbe (első futáskor e-mail + jelszó + MFA, utána a mentett tokennel)
  2. Listázza az utolsó N nap aktivitásait (azonosító, kezdés, típus, táv, idő)
  3. Listázza ugyanezen napok alvásadatait (alvás, mély, REM, ébren, nyug. HR, Body Battery)
  4. Egy nap nyers alvás-JSON-ját elmenti, hogy ellenőrizzük a mezőneveket
  5. --download ID: egy aktivitás eredeti .fit fájlját letölti

Telepítés:   pip3 install garminconnect
Futtatás:    python3 garmin_check.py              # utolsó 14 nap
             python3 garmin_check.py --days 30
             python3 garmin_check.py --download 12345678901
             python3 garmin_check.py --export-token   # a GitHub Secrethez (2. lépés)
"""
import argparse
import getpass
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

from garminconnect import Garmin

TOKENSTORE = Path("~/.garminconnect").expanduser()
OUTDIR = Path("~/Garmin").expanduser()


def connect() -> Garmin:
    if TOKENSTORE.exists():
        g = Garmin()
        g.login(str(TOKENSTORE))
        print(f"✓ Belépés mentett tokennel ({TOKENSTORE})")
        return g
    email = input("Garmin e-mail: ").strip()
    password = getpass.getpass("Garmin jelszó (nem jelenik meg): ")
    g = Garmin(email=email, password=password,
               prompt_mfa=lambda: input("MFA-kód: ").strip())
    g.login()
    TOKENSTORE.mkdir(mode=0o700, exist_ok=True)
    g.client.dump(str(TOKENSTORE))
    print(f"✓ Első belépés sikeres, token mentve: {TOKENSTORE}")
    return g


def hms(sec):
    if sec is None:
        return "—"
    sec = int(round(sec))
    h, m = divmod(sec // 60, 60)
    return f"{h}:{m:02d}" if h else f"0:{m:02d}"


def list_activities(g: Garmin, start: date, end: date):
    acts = g.get_activities_by_date(start.isoformat(), end.isoformat(), sortorder="asc")
    print(f"\n=== AKTIVITÁSOK {start} – {end}: {len(acts)} db ===")
    print(f"{'#':>2}  {'azonosító':<12} {'kezdés':<16} {'típus':<20} {'km':>6} {'idő':>6}  név")
    for i, a in enumerate(acts, 1):
        typ = (a.get("activityType") or {}).get("typeKey", "?")
        km = (a.get("distance") or 0) / 1000
        print(f"{i:>2}  {a.get('activityId'):<12} {str(a.get('startTimeLocal',''))[:16]:<16} "
              f"{typ:<20} {km:>6.2f} {hms(a.get('duration')):>6}  {a.get('activityName','')}")
    return acts


def list_sleep(g: Garmin, start: date, end: date):
    print(f"\n=== ALVÁS {start} – {end} (dátum = Garmin calendarDate, az ébredés napja) ===")
    print(f"{'dátum':<11} {'alvás':>6} {'mély':>6} {'REM':>6} {'ébren':>6} {'nyugHR':>6} {'BB':>5}")
    raw_saved = False
    d = start
    while d <= end:
        s = g.get_sleep_data(d.isoformat()) or {}
        dto = s.get("dailySleepDTO") or {}
        if not raw_saved and dto.get("sleepTimeSeconds"):
            OUTDIR.mkdir(exist_ok=True)
            p = OUTDIR / f"sleep_raw_{d}.json"
            p.write_text(json.dumps(s, indent=2, ensure_ascii=False))
            raw_saved = p
        bb = s.get("bodyBatteryChange")
        print(f"{d.isoformat():<11} {hms(dto.get('sleepTimeSeconds')):>6} "
              f"{hms(dto.get('deepSleepSeconds')):>6} {hms(dto.get('remSleepSeconds')):>6} "
              f"{hms(dto.get('awakeSleepSeconds')):>6} {str(s.get('restingHeartRate','—')):>6} "
              f"{('+' if (bb or 0) > 0 else '') + str(bb) if bb is not None else '—':>5}")
        d += timedelta(days=1)
    if raw_saved:
        print(f"\nNyers alvás-JSON mentve (mezőnév-ellenőrzéshez): {raw_saved}")


def download(g: Garmin, activity_id: str):
    data = g.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    OUTDIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            target = OUTDIR / f"{activity_id}_{Path(name).name}"
            target.write_bytes(z.read(name))
            print(f"✓ Letöltve: {target} ({target.stat().st_size/1024:.0f} KB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--download", metavar="ACTIVITY_ID")
    ap.add_argument("--export-token", action="store_true",
                    help="kiírja a tokent JSON-ként a GitHub Secrethez")
    args = ap.parse_args()

    g = connect()
    if args.export_token:
        print("\n--- GARMINTOKENS (ezt másold a GitHub Secretbe, sehova máshova) ---")
        print(g.client.dumps())
        return
    if args.download:
        download(g, args.download)
        return
    end = date.today()
    start = end - timedelta(days=args.days - 1)
    list_activities(g, start, end)
    list_sleep(g, start, end)


if __name__ == "__main__":
    main()
