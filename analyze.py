"""A .fit fájlok elemzése a napló oszlopaihoz.
Szabályok az Edzés-értékelések chatben kialakított edzes.sh alapján."""
import io
from fitparse import FitFile

ROUTE_KM = 16.1        # az ingázási útvonal hossza
CITY_KM = 6.0          # városi szakasz: reggel az UTOLSÓ, délután az ELSŐ 6 km
ROUTE_TOL_KM = 0.5     # ennél nagyobb eltérés = más útvonal, nem összehasonlítható
MAX_GAP_S = 5          # ennél hosszabb rés a rekordok között = állás, nem számít


# ---------------------------------------------------------------- beolvasás
def load(fit_bytes: bytes):
    ff = FitFile(io.BytesIO(fit_bytes))
    sess = {}
    for m in ff.get_messages("session"):
        sess = {f.name: f.value for f in m}
        break
    recs = []
    for m in ff.get_messages("record"):
        r = {f.name: f.value for f in m}
        if r.get("timestamp") is not None:
            if r.get("altitude") is None and r.get("enhanced_altitude") is not None:
                r["altitude"] = r["enhanced_altitude"]
            recs.append(r)
    # idősúly és mozgásidő-tengely
    t = 0.0
    for i, r in enumerate(recs):
        if i + 1 < len(recs):
            dt = (recs[i + 1]["timestamp"] - r["timestamp"]).total_seconds()
            r["_w"] = dt if 0 < dt <= MAX_GAP_S else 1.0
        else:
            r["_w"] = 1.0
        r["_t"] = t
        t += r["_w"]
    return sess, recs


# ---------------------------------------------------------------- segédek
def _vals(rs, k):
    return [(r[k], r["_w"]) for r in rs if r.get(k) is not None]


def wavg(rs, k):
    v = _vals(rs, k)
    w = sum(x[1] for x in v)
    return sum(a * b for a, b in v) / w if w else None


def vmax(rs, k):
    v = [r[k] for r in rs if r.get(k) is not None]
    return max(v) if v else None


def minutes(rs, cond):
    return round(sum(r["_w"] for r in rs if cond(r)) / 60, 1)


def has_power(rs):
    return any((r.get("power") or 0) > 0 for r in rs)


def power_stats(rs):
    if not has_power(rs):
        return None
    p = [r.get("power") or 0 for r in rs]
    avg = sum(p) / len(p)
    if len(p) >= 30:
        roll = []
        s = sum(p[:30])
        roll.append(s / 30)
        for i in range(30, len(p)):
            s += p[i] - p[i - 30]
            roll.append(s / 30)
        np_ = (sum(x ** 4 for x in roll) / len(roll)) ** 0.25
    else:
        np_ = avg
    pco = [r["left_pco"] for r in rs if r.get("left_pco") not in (None, 0)]
    return {
        "W": round(avg), "NP": round(np_), "VI": round(np_ / avg, 2) if avg else None,
        "p_220W": minutes(rs, lambda r: (r.get("power") or 0) > 220),
        "PCO_bal_mm": round(sum(pco) / len(pco), 1) if pco else None,
    }


def seg_stats(rs):
    if len(rs) < 60:
        return None
    d = (rs[-1]["distance"] - rs[0]["distance"]) / 1000
    t = sum(r["_w"] for r in rs)
    out = {"km": round(d, 2), "perc": round(t / 60, 1),
           "HR": round(wavg(rs, "heart_rate") or 0), "HRmax": vmax(rs, "heart_rate"),
           "kmh": round(d / (t / 3600), 1) if t else None,
           "p_135": minutes(rs, lambda r: (r.get("heart_rate") or 0) > 135)}
    if has_power(rs):
        out["W"] = round(sum(r.get("power") or 0 for r in rs) / len(rs))
    return out


def mmss(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def hmmss(sec):
    sec = int(round(sec or 0))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else mmss(sec)


def temp_range(rs, sess):
    a = sess.get("avg_temperature")
    m = sess.get("max_temperature")
    if a is None:
        a = wavg(rs, "temperature")
    if m is None:
        m = vmax(rs, "temperature")
    return f"{round(a)}–{round(m)}" if a is not None and m is not None else None


def per_minute(rs, start_min, end_min):
    """Percenkénti bontás: W, HR, meredekség, kadencia, mp 135 felett."""
    out = []
    for mi in range(start_min, end_min):
        s = [r for r in rs if mi * 60 <= r["_t"] < (mi + 1) * 60]
        if len(s) < 20:
            continue
        a = [r["altitude"] for r in s if r.get("altitude") is not None]
        dd = (s[-1].get("distance") or 0) - (s[0].get("distance") or 0)
        g = (a[-1] - a[0]) / dd * 100 if dd > 20 and len(a) > 1 else None
        row = {"perc": mi, "HR": round(wavg(s, "heart_rate") or 0),
               "lejto_%": round(g, 1) if g is not None else None,
               "kad": round(wavg(s, "cadence") or 0),
               "mp_135": int(sum(r["_w"] for r in s if (r.get("heart_rate") or 0) > 135))}
        if has_power(s):
            row["W"] = round(sum(r.get("power") or 0 for r in s) / len(s))
        out.append(row)
    return out


# ---------------------------------------------------------------- típusok
def commute(sess, recs, mode):
    R = [r for r in recs if r.get("heart_rate") and r.get("distance") is not None]
    tot = R[-1]["distance"]
    if mode == "odaut":
        kul = [r for r in R if r["distance"] < tot - CITY_KM * 1000]
        var = [r for r in R if r["distance"] >= tot - CITY_KM * 1000]
    else:
        var = [r for r in R if r["distance"] < CITY_KM * 1000]
        kul = [r for r in R if r["distance"] >= CITY_KM * 1000]
    km = (sess.get("total_distance") or tot) / 1000
    timer = sess.get("total_timer_time") or sum(r["_w"] for r in R)
    hr = lambda r: r.get("heart_rate") or 0
    out = {
        "tipus": mode,
        "datum": str(sess.get("start_time", R[0]["timestamp"]))[:10],
        "tav_km": round(km, 2), "ido": mmss(timer),
        "ido_teljes": mmss(sess.get("total_elapsed_time")),
        "atl_kmh": round(km / (timer / 3600), 1),
        "atl_HR": round(wavg(R, "heart_rate")), "max_HR": vmax(R, "heart_rate"),
        "kulter": seg_stats(kul), "varos": seg_stats(var),
        "hom_C": temp_range(R, sess),
        "emelkedes_m": sess.get("total_ascent"), "lejtes_m": sess.get("total_descent"),
        "teljesitmeny": power_stats(R),
        "mas_utvonal": abs(km - ROUTE_KM) > ROUTE_TOL_KM,
    }
    if mode == "odaut":
        out["p_125"] = minutes(R, lambda r: hr(r) > 125)
        out["p_135"] = minutes(R, lambda r: hr(r) > 135)
    else:
        out["p_135"] = minutes(R, lambda r: hr(r) > 135)
        out["p_140"] = minutes(R, lambda r: hr(r) > 140)
        tot_w = sum(r["_w"] for r in R)
        out["celsav_pct"] = round(sum(r["_w"] for r in R if 125 <= hr(r) <= 135) / tot_w * 100)
        out["mp_135_0_44"] = int(sum(r["_w"] for r in R if r["_t"] < 44 * 60 and hr(r) > 135))
        q = R[-1]["_t"] / 4
        out["negyedek_HR"] = [round(wavg([r for r in R if i * q <= r["_t"] < (i + 1) * q],
                                         "heart_rate") or 0) for i in range(4)]
        end_min = int(R[-1]["_t"] // 60) + 1
        out["ordogarok_35_46"] = per_minute(R, 35, 46)
        out["zaro_50_vege"] = per_minute(R, 50, end_min)
    return out


def efficiency_index(R):
    """VAM/HR a 4%-nál meredekebb 60 mp-es ablakokon, 30 perces blokkokban."""
    blocks = {}
    for mi in range(int(R[-1]["_t"] // 60)):
        s = [r for r in R if mi * 60 <= r["_t"] < (mi + 1) * 60]
        if len(s) < 30:
            continue
        a = [r["altitude"] for r in s if r.get("altitude") is not None]
        dd = (s[-1].get("distance") or 0) - (s[0].get("distance") or 0)
        if len(a) < 2 or dd < 50:
            continue
        g = (a[-1] - a[0]) / dd * 100
        h = wavg(s, "heart_rate")
        if g > 4 and h:
            vam = (a[-1] - a[0]) * 60  # m/óra
            blocks.setdefault(mi // 30, []).append(vam / h)
    return {f"{b * 30}-{b * 30 + 30}": round(sum(v) / len(v), 2) for b, v in sorted(blocks.items())}


def endurance(sess, recs, indoor):
    R = [r for r in recs if r.get("heart_rate")]
    timer = sess.get("total_timer_time") or sum(r["_w"] for r in R)
    hr = lambda r: r.get("heart_rate") or 0
    tot_w = sum(r["_w"] for r in R)
    out = {
        "tipus": "gorgo" if indoor else "hosszu",
        "datum": str(sess.get("start_time", R[0]["timestamp"]))[:10],
        "ido": hmmss(timer), "atl_HR": round(wavg(R, "heart_rate")), "max_HR": vmax(R, "heart_rate"),
        "kcal": sess.get("total_calories"),
        "tav_km": round((sess.get("total_distance") or 0) / 1000, 2),
        "emelkedes_m": sess.get("total_ascent"),
        "hom_C": temp_range(R, sess),
        "teljesitmeny": power_stats(R),
        "HR_110_140_pct": round(sum(r["_w"] for r in R if 110 <= hr(r) <= 140) / tot_w * 100),
        "HR_120_140_pct": round(sum(r["_w"] for r in R if 120 <= hr(r) <= 140) / tot_w * 100),
        "p_140": minutes(R, lambda r: hr(r) > 140),
        "kadencia": round(wavg(R, "cadence") or 0),
    }
    if has_power(R):
        # dekoppling: (EF2/EF1 - 1)*100, EF = átl. W / átl. HR; az első 10 perc nélkül
        body = [r for r in R if r["_t"] >= 600]
        if len(body) > 1200:
            mid = body[len(body) // 2]["_t"]
            ef = []
            for half in ([r for r in body if r["_t"] < mid], [r for r in body if r["_t"] >= mid]):
                ef.append((sum(r.get("power") or 0 for r in half) / len(half)) / wavg(half, "heart_rate"))
            out["dekoppling_pct"] = round((ef[1] / ef[0] - 1) * 100, 1)
    if not indoor:
        out["hatekonysagi_index"] = efficiency_index([r for r in R if r.get("distance") is not None])
    return out


def generic(sess, recs):
    R = [r for r in recs if r.get("heart_rate")]
    return {
        "tipus": "egyeb",
        "datum": str(sess.get("start_time", recs[0]["timestamp"]))[:10],
        "tav_km": round((sess.get("total_distance") or 0) / 1000, 2),
        "ido": hmmss(sess.get("total_timer_time")),
        "emelkedes_m": sess.get("total_ascent"),
        "atl_HR": round(wavg(R, "heart_rate")) if R else None, "max_HR": vmax(R, "heart_rate"),
        "hom_C": temp_range(recs, sess),
        "teljesitmeny": power_stats(recs),
    }


def analyze(fit_bytes: bytes, category: str) -> dict:
    sess, recs = load(fit_bytes)
    if not recs:
        return {"tipus": category, "hiba": "nincs rekord a fájlban"}
    if category in ("odaut", "hazaut"):
        return commute(sess, recs, category)
    if category in ("gorgo", "hosszu"):
        return endurance(sess, recs, indoor=(category == "gorgo"))
    return generic(sess, recs)
