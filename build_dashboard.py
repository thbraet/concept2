#!/usr/bin/env python3
"""Generate dashboard.html from workouts.json."""

import json
from datetime import datetime
from pathlib import Path

WORKOUTS_FILE = Path("workouts.json")
workouts_raw = json.loads(WORKOUTS_FILE.read_text())

# Per-stroke samples, columnar by workout id (written by fetch_workouts.py).
# Optional: the dashboard still builds (with per-split charts) if it's absent.
STROKES_FILE = Path("strokes.json")
strokes_raw = json.loads(STROKES_FILE.read_text()) if STROKES_FILE.exists() else {}

# User profile (weight, max HR) for watts/kg and %HRmax. Optional.
PROFILE_FILE = Path("profile.json")
profile = json.loads(PROFILE_FILE.read_text()) if PROFILE_FILE.exists() else {}

# When the underlying data was last fetched (file mtime), shown in the header.
generated_at = datetime.fromtimestamp(WORKOUTS_FILE.stat().st_mtime).strftime("%d %b %Y, %H:%M")

# Heart-rate readings known to be bad (faulty monitor) — HR is dropped so it is
# excluded from the chart, trend line, and average. Add workout ids here as needed.
EXCLUDED_HR_IDS = {
    117246434,  # 2026-06-05 06:24 — HR monitor glitch (recorded 19 bpm)
}

def pace_seconds(workout):
    """Return pace as seconds per 500m, or None."""
    dist = workout.get("distance", 0)
    t = workout.get("time", 0)  # tenths of a second
    if not dist:
        return None
    return (t / 10 / dist) * 500

def fmt_pace(sec):
    """Format seconds-per-500m as M:SS.f"""
    if sec is None:
        return "—"
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:04.1f}"

def fmt_duration(t_tenths):
    total_sec = t_tenths / 10
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = total_sec % 60
    if h:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"

def split_pace_seconds(distance, time_tenths):
    """Pace as seconds per 500m for a split, or None."""
    if not distance:
        return None
    return (time_tenths / 10 / distance) * 500

def avg_watts(wattminutes, time_tenths):
    """Average power in watts from watt-minutes over an elapsed time."""
    minutes = time_tenths / 10 / 60
    if not minutes:
        return None
    return wattminutes / minutes

def build_detail(w):
    """Full per-workout payload: whole-session averages plus per-split series."""
    hr = w.get("heart_rate") or {}
    drop_hr = w["id"] in EXCLUDED_HR_IDS

    raw_splits = (w.get("workout") or {}).get("splits") or []
    splits = []
    cum_dist = 0
    cum_time = 0  # tenths
    for i, s in enumerate(raw_splits):
        t = s.get("time", 0)
        dist = s.get("distance", 0)
        cum_dist += dist
        cum_time += t
        shr = s.get("heart_rate") or {}
        pace = split_pace_seconds(dist, t)
        splits.append({
            "idx":          i + 1,
            "time":         t,
            "duration":     fmt_duration(t),
            "distance":     dist,
            "cum_distance": cum_dist,
            "cum_time_sec": round(cum_time / 10, 1),
            "pace_sec":     round(pace, 2) if pace else None,
            "pace_fmt":     fmt_pace(pace),
            "watts":        round(avg_watts(s.get("wattminutes_total", 0), t) or 0) or None,
            "stroke_rate":  s.get("stroke_rate"),
            "calories":     s.get("calories_total"),
            "hr_avg":       (shr.get("average") or None) if not drop_hr else None,
            "hr_max":       (shr.get("max") or None) if not drop_hr else None,
            "hr_min":       (shr.get("min") or None) if not drop_hr else None,
        })

    pace_sec = pace_seconds(w)
    return {
        "id":           w["id"],
        "date":         w["date"],
        "workout_type": w.get("workout_type", ""),
        "type":         w.get("type", ""),
        "source":       w.get("source", ""),
        "distance":     w["distance"],
        "time":         w["time"],
        "duration":     fmt_duration(w["time"]),
        "pace_sec":     round(pace_sec, 2) if pace_sec else None,
        "pace_fmt":     fmt_pace(pace_sec),
        "avg_watts":    round(avg_watts(w.get("wattminutes_total", 0), w["time"]) or 0) or None,
        "watts_est":    bool(w.get("wattminutes_estimated")),
        "calories":     w.get("calories_total"),
        "stroke_count": w.get("stroke_count"),
        "stroke_rate":  w.get("stroke_rate"),
        "drag_factor":  w.get("drag_factor"),
        "weight_class": w.get("weight_class"),
        "avg_hr":       (hr.get("average") or None) if not drop_hr else None,
        "max_hr":       (hr.get("max") or None) if not drop_hr else None,
        "min_hr":       (hr.get("min") or None) if not drop_hr else None,
        "ending_hr":    (hr.get("ending") or None) if not drop_hr else None,
        "recovery_hr":  (hr.get("recovery") or None) if not drop_hr else None,
        "targets":      (w.get("workout") or {}).get("targets") or {},
        "splits":       splits,
    }

WEIGHT_KG = profile.get("weight_kg")
HR_MAX    = profile.get("max_heart_rate")

def aggregate_metrics(w, avg_hr):
    """One representative number per metric for a whole workout.

    Aggregation is chosen per metric to be the physically correct summary,
    not a naive mean of per-stroke samples:
      • pace        — distance-weighted average (total time / total distance)
      • power       — average watts (total work / total time)
      • watts/kg    — average watts / body weight
      • meters/strk — total distance / total stroke count
      • work/stroke — total work (J) / total stroke count
      • cal/hr      — total calories / total hours
      • HR, %HRmax, stroke rate — the workout's recorded averages
      • calories    — total (it is already a per-workout total)
    """
    t_tenths = w.get("time", 0)
    minutes  = t_tenths / 10 / 60
    hours    = minutes / 60
    dist     = w.get("distance", 0)
    wattmin  = w.get("wattminutes_total", 0)
    strokes  = w.get("stroke_count") or 0
    cal      = w.get("calories_total")
    watts    = (wattmin / minutes) if minutes else None

    return {
        "hrpct": round(avg_hr / HR_MAX * 100, 1) if (avg_hr and HR_MAX) else None,
        "dps":   round(dist / strokes, 2) if strokes else None,
        "watts": round(watts) if watts else None,
        "wkg":   round(watts / WEIGHT_KG, 2) if (watts and WEIGHT_KG) else None,
        "work":  round(wattmin * 60 / strokes) if strokes else None,   # joules / stroke
        "calhr": round(cal / hours) if (cal and hours) else None,
    }

def _mean_sd(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    mean = sum(v) / len(v)
    sd = (sum((x - mean) ** 2 for x in v) / len(v)) ** 0.5
    return mean, sd

def _stroke_watts(p):
    """Instantaneous watts from a pace sample (tenths-sec / 500 m), cube law."""
    if not p or p <= 0:
        return None
    mps = (p / 10) / 500          # seconds per metre
    return 2.80 / (mps ** 3)

def effort_metrics(w):
    """Per-workout effort-quality summaries, mirroring the detail view's
    renderEffortCards() so the dashboard can chart their evolution:

      • pace_cv     — coefficient of variation of /500m pace (%, lower = steadier)
      • spm_cv      — coefficient of variation of stroke rate (%, lower = steadier)
      • pace_fade   — 2nd- vs 1st-half mean pace (%, negative = negative split)
      • decoupling  — aerobic decoupling, 1st- vs 2nd-half power:HR drift (%)

    Prefers per-stroke samples and falls back to per-split averages; returns
    None for any metric whose inputs are missing.
    """
    s = strokes_raw.get(str(w["id"]))
    t, power, hr, pace, spm = [], [], [], [], []
    if s and s.get("t"):
        st, sp, shr, sspm = s.get("t", []), s.get("p", []), s.get("hr", []), s.get("spm", [])
        for i in range(len(st)):
            t.append(st[i] / 10)
            pv = sp[i] if i < len(sp) else 0
            power.append(_stroke_watts(pv))
            pace.append(pv / 10 if pv and pv > 0 else None)
            hr.append(shr[i] if i < len(shr) and shr[i] else None)
            spm.append(sspm[i] if i < len(sspm) and sspm[i] else None)
    else:
        acc = 0
        for sp in (w.get("workout") or {}).get("splits") or []:
            tt = sp.get("time", 0)
            acc += tt / 10
            t.append(acc)
            power.append(round(avg_watts(sp.get("wattminutes_total", 0), tt) or 0) or None)
            p = split_pace_seconds(sp.get("distance", 0), tt)
            pace.append(round(p, 2) if p else None)
            shr = sp.get("heart_rate") or {}
            hr.append(shr.get("average") or None)
            spm.append(sp.get("stroke_rate"))

    out = {"pace_cv": None, "spm_cv": None, "pace_fade": None, "decoupling": None}
    if not t:
        return out

    pc = _mean_sd(pace)
    if pc and pc[0]:
        out["pace_cv"] = round(pc[1] / pc[0] * 100, 1)
    sc = _mean_sd(spm)
    if sc and sc[0]:
        out["spm_cv"] = round(sc[1] / sc[0] * 100, 1)

    # Split at the time midpoint for fade / decoupling.
    mid = t[-1] / 2
    first_pace, second_pace, first_ef, second_ef = [], [], [], []
    for i in range(len(t)):
        first = t[i] <= mid
        if pace[i] is not None:
            (first_pace if first else second_pace).append(pace[i])
        if power[i] is not None and hr[i] and hr[i] > 0:
            (first_ef if first else second_ef).append(power[i] / hr[i])
    fp, spc = _mean_sd(first_pace), _mean_sd(second_pace)
    if fp and spc and fp[0]:
        out["pace_fade"] = round((spc[0] - fp[0]) / fp[0] * 100, 1)
    f1, f2 = _mean_sd(first_ef), _mean_sd(second_ef)
    if f1 and f2 and f1[0]:
        out["decoupling"] = round((f1[0] - f2[0]) / f1[0] * 100, 1)
    return out

# ── Watt-minute backfill ─────────────────────────────────────────────────────
# Concept2's Logbook only began storing `wattminutes_total` for results from
# 2026-05-12 onward; earlier workouts lack it entirely (confirmed against the
# individual-result API endpoint). Without it, Power, Watts/kg and Work/Stroke
# are blank for every older session. We reconstruct it from the per-stroke pace
# samples we already fetch, using Concept2's cube law watts = 2.80 / (s/m)³.
#
# Integrating *sampled* pace underestimates true work by a steady ~6% (power is
# convex in speed, so snapshots miss the peaks — Jensen's inequality). Rather
# than hardcode a fudge factor, we self-calibrate: the ratio of measured to
# reconstructed watt-minutes over every workout that has *both* is applied to
# the workouts that have only strokes. On the current data this lands the
# estimate within ~1% of the real value.

def _stroke_wattmin_increments(s):
    """Per-interval watt-minutes from a workout's stroke samples.

    Returns a list of (elapsed_end_tenths, wattminutes) so the increments can
    be both summed (whole-session total) and bucketed into splits.
    """
    t = s.get("t") or []
    p = s.get("p") or []
    out = []
    prev = 0  # elapsed time starts at 0 tenths
    for i in range(len(t)):
        dt_sec = (t[i] - prev) / 10.0
        prev = t[i]
        pv = p[i] if i < len(p) else None
        if pv and pv > 0 and dt_sec > 0:
            sec_per_m = pv / 5000.0            # tenths-sec/500m -> sec/m
            watts = 2.80 / sec_per_m**3
            out.append((t[i], watts * dt_sec / 60.0))
    return out

# Self-calibration factor from workouts carrying both measured and recon values.
_cal_real = _cal_rec = 0.0
for _w in workouts_raw:
    _s = strokes_raw.get(str(_w["id"]))
    if _s is not None and _w.get("wattminutes_total") is not None:
        _rec = sum(wm for _, wm in _stroke_wattmin_increments(_s))
        if _rec > 0:
            _cal_real += _w["wattminutes_total"]
            _cal_rec  += _rec
WATTMIN_CALIBRATION = (_cal_real / _cal_rec) if _cal_rec else 1.0

# Backfill workouts (and their splits) that lack a measured value.
backfilled_count = 0
for _w in workouts_raw:
    if _w.get("wattminutes_total") is not None:
        continue
    _s = strokes_raw.get(str(_w["id"]))
    if _s is None:
        continue
    _inc = _stroke_wattmin_increments(_s)
    if not _inc:
        continue
    _w["wattminutes_total"] = round(sum(wm for _, wm in _inc) * WATTMIN_CALIBRATION)
    _w["wattminutes_estimated"] = True
    backfilled_count += 1

    # Distribute into splits by elapsed-time bucket so the detail drill-down's
    # per-split Power column stays consistent with the session total.
    raw_splits = (_w.get("workout") or {}).get("splits") or []
    if raw_splits:
        bounds, acc = [], 0
        for sp in raw_splits:
            acc += sp.get("time", 0)
            bounds.append(acc)  # cumulative split end times (tenths)
        per_split = [0.0] * len(raw_splits)
        for t_end, wm in _inc:
            bi = next((j for j, b in enumerate(bounds) if t_end <= b), len(bounds) - 1)
            per_split[bi] += wm
        for sp, val in zip(raw_splits, per_split):
            sp["wattminutes_total"] = round(val * WATTMIN_CALIBRATION)

if backfilled_count:
    print(f"Backfilled wattminutes_total for {backfilled_count} workouts "
          f"(calibration ×{WATTMIN_CALIBRATION:.4f})")
# ─────────────────────────────────────────────────────────────────────────────

rows = []
details = {}
for w in workouts_raw:
    pace_sec = pace_seconds(w)
    hr = w.get("heart_rate") or {}
    avg_hr = hr.get("average") if hr else None
    if w["id"] in EXCLUDED_HR_IDS:
        avg_hr = None
    rows.append({
        "id":       w["id"],
        "date":     w["date"],
        "distance": w["distance"],
        "duration": fmt_duration(w["time"]),
        "pace_sec": round(pace_sec, 2) if pace_sec else None,
        "pace_fmt": fmt_pace(pace_sec),
        "avg_hr":   avg_hr,
        "workout_type": w.get("workout_type", ""),
        "calories": w.get("calories_total"),
        "stroke_rate": w.get("stroke_rate"),
        "est":      bool(w.get("wattminutes_estimated")),
        **aggregate_metrics(w, avg_hr),
        **effort_metrics(w),
    })
    details[str(w["id"])] = build_detail(w)

# Sort by date ascending for the chart
chart_rows = sorted(rows, key=lambda r: r["date"])

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Rowing Dashboard — Thibauld Braet</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
      min-height: 100vh;
    }}

    header {{
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
      color: #fff;
      padding: 28px 40px;
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    header svg {{ flex-shrink: 0; }}
    header h1 {{ font-size: 1.6rem; font-weight: 700; letter-spacing: -0.3px; }}
    header p  {{ font-size: 0.85rem; opacity: 0.65; margin-top: 2px; }}

    .header-actions {{ margin-left: auto; text-align: right; }}
    .refresh-btn {{
      background: #e94560; color: #fff; border: none; border-radius: 8px;
      padding: 9px 16px; font-size: 0.85rem; font-weight: 600; cursor: pointer;
      font-family: inherit; transition: background .15s, opacity .15s;
    }}
    .refresh-btn:hover:not(:disabled) {{ background: #d63651; }}
    .refresh-btn:disabled {{ opacity: .6; cursor: default; }}
    .last-updated {{ font-size: 0.72rem; opacity: .6; margin-top: 7px; }}

    .main {{ max-width: 1300px; margin: 0 auto; padding: 32px 24px 64px; }}

    /* ── Filter bar ── */
    .filter-bar {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      background: #fff;
      border-radius: 12px;
      padding: 14px 20px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      margin-bottom: 20px;
    }}
    .filter-label {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
                     letter-spacing: .6px; color: #888; }}
    .filter-bar input[type="date"] {{
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      padding: 6px 10px;
      font-size: 0.85rem;
      font-family: inherit;
      color: #1a1a2e;
      outline: none;
      transition: border-color .15s;
    }}
    .filter-bar input[type="date"]:focus {{ border-color: #0f3460; }}
    .filter-sep {{ color: #aaa; }}
    .filter-bar button {{
      background: none; border: 1px solid #e0e0e0; border-radius: 8px;
      padding: 6px 14px; cursor: pointer; font-size: 0.82rem; color: #555;
      transition: all .15s;
    }}
    .filter-bar button:hover {{ background: #0f3460; color: #fff; border-color: #0f3460; }}
    #filter-summary {{ font-size: 0.8rem; color: #aaa; margin-left: auto; }}

    /* ── Stat cards ── */
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .card {{
      background: #fff;
      border-radius: 12px;
      padding: 20px 22px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
    }}
    .card-label {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
                   letter-spacing: .6px; color: #888; margin-bottom: 6px; }}
    .card-value {{ font-size: 1.7rem; font-weight: 700; color: #0f3460; line-height: 1; }}
    .card-sub   {{ font-size: 0.78rem; color: #aaa; margin-top: 4px; }}

    /* ── Chart panel ── */
    .panel {{
      background: #fff;
      border-radius: 14px;
      padding: 28px 28px 20px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      margin-bottom: 32px;
    }}
    .panel-title {{
      font-size: 1rem; font-weight: 700; margin-bottom: 20px; color: #1a1a2e;
    }}
    .chart-wrap {{ position: relative; height: 320px; }}

    /* ── Effort-quality small multiples ── */
    .effort-trend-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 20px;
    }}
    @media (max-width: 720px) {{ .effort-trend-grid {{ grid-template-columns: 1fr; }} }}
    .effort-trend {{
      border: 1px solid #eef0f3;
      border-radius: 10px;
      padding: 14px 16px 10px;
    }}
    .effort-trend-head {{
      display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
    }}
    .effort-trend-label {{ font-size: 0.82rem; font-weight: 700; color: #1a1a2e; }}
    .effort-trend-latest {{ font-size: 0.95rem; font-weight: 700; }}
    .effort-trend-canvas {{ position: relative; height: 150px; margin-top: 8px; }}
    .effort-trend-note {{ font-size: 0.7rem; color: #aaa; margin-top: 8px; }}

    /* ── Table ── */
    .table-wrap {{
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      overflow: hidden;
    }}
    .table-header {{
      padding: 20px 24px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .table-header h2 {{ font-size: 1rem; font-weight: 700; }}
    .table-header input {{
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      padding: 7px 14px;
      font-size: 0.85rem;
      outline: none;
      width: 220px;
      transition: border-color .15s;
    }}
    .table-header input:focus {{ border-color: #0f3460; }}

    table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
    thead th {{
      background: #f8f9fb;
      padding: 10px 16px;
      text-align: left;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .5px;
      color: #888;
      border-bottom: 1px solid #eee;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}
    thead th:hover {{ color: #0f3460; }}
    thead th.sorted {{ color: #0f3460; }}
    thead th .sort-icon {{ margin-left: 4px; opacity: .5; }}
    thead th.sorted .sort-icon {{ opacity: 1; }}

    tbody tr {{ border-bottom: 1px solid #f2f3f5; transition: background .1s; }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #f8f9ff; }}
    tbody td {{ padding: 11px 16px; }}

    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 0.72rem;
      font-weight: 600;
      background: #e8f4fd;
      color: #0f3460;
    }}

    .pace-dot {{
      display: inline-block; width: 10px; height: 10px;
      border-radius: 50%; margin-right: 6px; vertical-align: middle;
    }}
    .hr-pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .hr-z1 {{ background:#e8f5e9; color:#2e7d32; }}
    .hr-z2 {{ background:#fff8e1; color:#f57f17; }}
    .hr-z3 {{ background:#fce4ec; color:#c62828; }}
    .hr-na {{ background:#f5f5f5; color:#aaa; }}

    .pagination {{
      display: flex; align-items: center; justify-content: flex-end;
      gap: 8px; padding: 14px 24px;
      border-top: 1px solid #f2f3f5;
      font-size: 0.82rem; color: #888;
    }}
    .pagination button {{
      background: none; border: 1px solid #e0e0e0; border-radius: 6px;
      padding: 4px 12px; cursor: pointer; font-size: 0.82rem;
      transition: all .15s;
    }}
    .pagination button:hover:not(:disabled) {{
      background: #0f3460; color: #fff; border-color: #0f3460;
    }}
    .pagination button:disabled {{ opacity: .35; cursor: default; }}
    #page-info {{ min-width: 80px; text-align: center; }}

    /* ── Clickable rows / detail view ── */
    tbody tr.clickable {{ cursor: pointer; }}
    tbody tr.clickable td:first-child {{ position: relative; }}
    .row-chevron {{ color: #ccc; font-weight: 700; }}
    tbody tr.clickable:hover .row-chevron {{ color: #0f3460; }}

    #view-detail {{ display: none; }}
    body.detail #view-list {{ display: none; }}
    body.detail #view-detail {{ display: block; }}

    .back-btn {{
      background: none; border: 1px solid #e0e0e0; border-radius: 8px;
      padding: 7px 14px; cursor: pointer; font-size: 0.85rem; color: #555;
      font-family: inherit; transition: all .15s; margin-bottom: 20px;
    }}
    .back-btn:hover {{ background: #0f3460; color: #fff; border-color: #0f3460; }}

    .detail-head {{ margin-bottom: 24px; }}
    .detail-head h2 {{ font-size: 1.4rem; font-weight: 700; color: #1a1a2e; }}
    .detail-head .meta {{ font-size: 0.85rem; color: #888; margin-top: 4px; }}
    .detail-head .badge {{ margin-left: 8px; }}

    .metric-toggle {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }}
    .metric-toggle button {{
      background: #f4f5f8; border: 1px solid #e6e8ec; border-radius: 8px;
      padding: 6px 14px; cursor: pointer; font-size: 0.82rem; color: #555;
      font-family: inherit; font-weight: 600; transition: all .12s;
    }}
    .metric-toggle button:hover {{ border-color: #0f3460; }}
    .metric-toggle button.active {{ background: #0f3460; color: #fff; border-color: #0f3460; }}

    /* ── Chart axis / overlay controls ── */
    .chart-controls {{ display: flex; gap: 20px; flex-wrap: wrap; align-items: center; margin-bottom: 18px; }}
    .chart-controls label {{ font-size: 0.78rem; color: #555; font-weight: 600;
                             display: flex; align-items: center; gap: 8px;
                             text-transform: uppercase; letter-spacing: .4px; }}
    .chart-controls select {{
      font-family: inherit; font-size: 0.85rem; font-weight: 500; text-transform: none;
      letter-spacing: 0; padding: 6px 10px; border: 1px solid #e0e0e0; border-radius: 8px;
      background: #fff; color: #1a1a2e; cursor: pointer; outline: none; transition: border-color .15s;
    }}
    .chart-controls select:focus {{ border-color: #0f3460; }}
    .chart-controls .split-toggle {{ cursor: pointer; }}
    .chart-controls input[type="checkbox"] {{ width: 16px; height: 16px; accent-color: #0f3460; cursor: pointer; }}
    .chart-controls label.disabled {{ opacity: .35; cursor: default; }}

    .splits-note {{ padding: 28px; text-align: center; color: #aaa; font-size: 0.9rem; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    th.num {{ text-align: right; }}
  </style>
</head>
<body>

<header>
  <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
    <circle cx="18" cy="18" r="18" fill="#e94560" opacity=".15"/>
    <path d="M6 22c3-4 6-6 9-6s6 4 9 2" stroke="#e94560" stroke-width="2.5"
          stroke-linecap="round" fill="none"/>
    <circle cx="18" cy="14" r="3" fill="#e94560" opacity=".8"/>
  </svg>
  <div>
    <h1>Rowing Dashboard</h1>
    <p>Thibauld Braet · Concept2 Logbook</p>
  </div>
  <div class="header-actions">
    <button id="refresh-btn" class="refresh-btn">↻ Refresh data</button>
    <p class="last-updated">Updated {generated_at}</p>
  </div>
</header>

<div class="main" id="view-list">

  <!-- Date filter -->
  <div class="filter-bar">
    <span class="filter-label">Date range</span>
    <input id="date-from" type="date" aria-label="From date" />
    <span class="filter-sep">→</span>
    <input id="date-to" type="date" aria-label="To date" />
    <button id="filter-reset">Reset</button>
    <span id="filter-summary"></span>
  </div>

  <!-- Stat cards -->
  <div class="cards" id="cards"></div>

  <!-- Chart -->
  <div class="panel">
    <div class="panel-title" id="main-chart-title">Trends across workouts</div>
    <div class="chart-controls">
      <label>Primary axis <select id="main-primary"></select></label>
      <label>Secondary axis <select id="main-secondary"></select></label>
      <label id="main-powermodel-label">Power model
        <select id="main-powermodel">
          <option value="energy">Energy (watt-min ÷ time)</option>
          <option value="pace">Pace formula (2.80/v³)</option>
        </select>
      </label>
      <span style="font-size:.75rem;color:#aaa;">one aggregated value per workout</span>
    </div>
    <div class="chart-wrap">
      <canvas id="chart"></canvas>
    </div>
  </div>

  <!-- Effort-quality trends -->
  <div class="panel">
    <div class="panel-title">Effort quality over time
      <span style="font-weight:400;color:#aaa;font-size:.8rem;">— one value per workout</span>
      <a href="aerobic-decoupling.html" target="_blank" style="font-weight:400;color:#0f3460;font-size:.78rem;margin-left:8px;text-decoration:none;">how aerobic decoupling works ↗</a>
    </div>
    <div class="effort-trend-grid" id="effort-trend-grid">
      <div class="effort-trend">
        <div class="effort-trend-head"><span class="effort-trend-label">Pace consistency</span><span class="effort-trend-latest" id="et-pacecv-latest" style="color:#0d9488"></span></div>
        <div class="effort-trend-canvas"><canvas id="et-pacecv"></canvas></div>
        <div class="effort-trend-note">CV of /500m pace · lower = steadier</div>
      </div>
      <div class="effort-trend">
        <div class="effort-trend-head"><span class="effort-trend-label">Stroke-rate consistency</span><span class="effort-trend-latest" id="et-spmcv-latest" style="color:#65a30d"></span></div>
        <div class="effort-trend-canvas"><canvas id="et-spmcv"></canvas></div>
        <div class="effort-trend-note">CV of stroke rate · lower = steadier</div>
      </div>
      <div class="effort-trend">
        <div class="effort-trend-head"><span class="effort-trend-label">Pace fade</span><span class="effort-trend-latest" id="et-pacefade-latest" style="color:#c026d3"></span></div>
        <div class="effort-trend-canvas"><canvas id="et-pacefade"></canvas></div>
        <div class="effort-trend-note">2nd vs 1st half · negative = negative split</div>
      </div>
      <div class="effort-trend">
        <div class="effort-trend-head"><span class="effort-trend-label">Aerobic decoupling</span><span class="effort-trend-latest" id="et-decouple-latest" style="color:#dc2626"></span></div>
        <div class="effort-trend-canvas"><canvas id="et-decouple"></canvas></div>
        <div class="effort-trend-note">Pw:Hr drift · &lt;5% strong aerobic base</div>
      </div>
    </div>
    <div class="splits-note" id="effort-trend-empty" style="display:none">Not enough per-stroke or per-split data in this range to chart effort quality.</div>
  </div>

  <!-- Power curve + projections from best efforts -->
  <div class="panel">
    <div class="panel-title">Power curve &amp; projected bests
      <span style="font-weight:400;color:#aaa;font-size:.8rem;">— mean-maximal power across every filtered workout</span>
    </div>
    <div class="splits-note" id="pc-note" style="margin-bottom:6px"></div>
    <div class="chart-wrap"><canvas id="pc-chart"></canvas></div>
    <div class="panel-title" style="margin-top:24px;font-size:.95rem">Projected race times
      <span style="font-weight:400;color:#aaa;font-size:.8rem;">— Riegel projection, anchored only on efforts ≥ 5 min</span>
      <a href="riegel-projection.html" target="_blank" style="font-weight:400;color:#0f3460;font-size:.78rem;margin-left:8px;text-decoration:none;">how the math works ↗</a>
    </div>
    <div class="chart-controls" style="margin-bottom:4px">
      <label>Anchor
        <select id="pc-anchor-mode">
          <option value="best">Best across anchors</option>
          <option value="nearest">Nearest-duration anchor</option>
        </select>
      </label>
      <span id="pc-anchor-hint" style="font-size:.75rem;color:#aaa;"></span>
    </div>
    <div class="cards" id="pc-proj-cards"></div>
  </div>

  <!-- Table -->
  <div class="table-wrap">
    <div class="table-header">
      <h2>All Workouts <span id="count-label" style="font-weight:400;color:#aaa;font-size:.85rem;"></span></h2>
      <input id="search" type="text" placeholder="Filter workouts…" />
    </div>
    <table>
      <thead>
        <tr>
          <th data-col="date">Date &amp; Time <span class="sort-icon">↕</span></th>
          <th data-col="distance">Distance <span class="sort-icon">↕</span></th>
          <th data-col="duration">Duration <span class="sort-icon">↕</span></th>
          <th data-col="pace_sec">Avg Pace <span class="sort-icon">↕</span></th>
          <th data-col="avg_hr">Avg HR <span class="sort-icon">↕</span></th>
          <th data-col="calories">Calories <span class="sort-icon">↕</span></th>
          <th data-col="stroke_rate">Stroke Rate <span class="sort-icon">↕</span></th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
    <div class="pagination">
      <span id="page-info"></span>
      <button id="prev-btn">← Prev</button>
      <button id="next-btn">Next →</button>
    </div>
  </div>

</div>

<!-- ── Single-workout detail view ── -->
<div class="main" id="view-detail">
  <button class="back-btn" id="back-btn">← Back to all workouts</button>

  <div class="detail-head">
    <h2 id="d-title">Workout</h2>
    <div class="meta" id="d-meta"></div>
  </div>

  <!-- Whole-workout averages / totals -->
  <div class="cards" id="d-cards"></div>

  <!-- Per-stroke / per-split time series -->
  <div class="panel">
    <div class="panel-title" id="d-chart-title">Metrics over time</div>
    <div class="chart-controls">
      <label>Primary axis <select id="d-primary"></select></label>
      <label>Secondary axis <select id="d-secondary"></select></label>
      <label class="split-toggle" id="d-splits-label"><input type="checkbox" id="d-show-splits" /> Split averages</label>
    </div>
    <div class="chart-wrap"><canvas id="d-chart"></canvas></div>
  </div>

  <!-- Effort & quality -->
  <div class="panel">
    <div class="panel-title">Effort &amp; quality
      <a href="aerobic-decoupling.html" target="_blank" style="font-weight:400;color:#0f3460;font-size:.78rem;margin-left:8px;text-decoration:none;">how aerobic decoupling works ↗</a>
    </div>
    <div class="cards" id="d-effort-cards"></div>
  </div>

  <!-- Splits table -->
  <div class="table-wrap">
    <div class="table-header"><h2>Splits <span id="d-split-count" style="font-weight:400;color:#aaa;font-size:.85rem;"></span></h2></div>
    <div id="d-splits-body"></div>
  </div>

  <!-- Projected race times (Riegel) -->
  <div class="panel" style="margin-top:32px">
    <div class="panel-title">Projected times <span style="font-weight:400;color:#aaa;font-size:.8rem;">— Riegel, from this piece</span>
      <a href="riegel-projection.html" target="_blank" style="font-weight:400;color:#0f3460;font-size:.78rem;margin-left:8px;text-decoration:none;">how the math works ↗</a>
    </div>
    <div class="cards" id="d-proj-cards"></div>
  </div>
</div>

<script>
const DATA = {json.dumps(rows, ensure_ascii=False)};
const CHART_DATA = {json.dumps(chart_rows, ensure_ascii=False)};
const DETAIL = {json.dumps(details, ensure_ascii=False)};
const STROKES = {json.dumps(strokes_raw, ensure_ascii=False)};
const PROFILE = {json.dumps(profile, ensure_ascii=False)};
const WATTMIN_CAL = {WATTMIN_CALIBRATION};

// ── Shared filter state ───────────────────────────────────────────────────────
const DEFAULT_DATE_FROM = "2026-04-27";  // default range start; end is open (latest)
let dateFrom = DEFAULT_DATE_FROM;   // "YYYY-MM-DD" or null
let dateTo   = null;   // "YYYY-MM-DD" or null
let searchQuery = "";

function inDateRange(r) {{
  const d = r.date.slice(0, 10);
  if (dateFrom && d < dateFrom) return false;
  if (dateTo   && d > dateTo)   return false;
  return true;
}}

function dateFiltered() {{ return DATA.filter(inDateRange); }}

function fmtPace(s) {{
  const m = Math.floor(s/60), sec = s%60;
  return `${{m}}:${{sec<10?'0':''}}${{sec.toFixed(1)}}/500m`;
}}

// h:mm:ss for long pieces, m:ss for short ones
function clockHMS(sec) {{
  const h = Math.floor(sec / 3600);
  const rem = sec - h * 3600;
  const m = Math.floor(rem / 60), s = Math.round(rem % 60);
  return h ? `${{h}}:${{m<10?'0':''}}${{m}}:${{s<10?'0':''}}${{s}}`
           : `${{m}}:${{s<10?'0':''}}${{s}}`;
}}

// Every distance / duration Concept2 ranks, in dropdown order. `dist` targets
// project a time; `time` targets project a distance.
const RANK_TARGETS = [
  {{ t:"time", s:60,     l:"1 min" }},
  {{ t:"time", s:240,    l:"4 min" }},
  {{ t:"time", s:1800,   l:"30 min" }},
  {{ t:"time", s:3600,   l:"60 min" }},
  {{ t:"dist", m:100,    l:"100 m" }},
  {{ t:"dist", m:500,    l:"500 m" }},
  {{ t:"dist", m:1000,   l:"1 000 m" }},
  {{ t:"dist", m:2000,   l:"2 000 m" }},
  {{ t:"dist", m:5000,   l:"5 000 m" }},
  {{ t:"dist", m:6000,   l:"6 000 m" }},
  {{ t:"dist", m:10000,  l:"10 000 m" }},
  {{ t:"dist", m:21097,  l:"Half marathon" }},
  {{ t:"dist", m:42195,  l:"Marathon" }},
  {{ t:"dist", m:100000, l:"100 000 m" }},
];
const RIEGEL_R = 1.06;

// Card sub-label for a projected effort: implied /500m pace + average power.
// Power is the cube law (watts = 2.80·v³) on the projected speed, which is the
// same scale as the calibrated power curve the projection is built from.
function projSub(speedMps) {{
  const watts = Math.round(2.80 * speedMps ** 3);
  return `${{fmtPace(500 / speedMps)}} · ${{watts}} W`;
}}

// ── Stat cards ──────────────────────────────────────────────────────────────
function renderCards(data) {{
  const total = data.length;
  const totalDist = data.reduce((a,r) => a + (r.distance||0), 0);
  const paces = data.map(r => r.pace_sec).filter(Boolean);
  const hrs   = data.map(r => r.avg_hr).filter(Boolean);
  const avgPace  = paces.length ? paces.reduce((a,b)=>a+b,0)/paces.length : null;
  const avgHR    = hrs.length   ? hrs.reduce((a,b)=>a+b,0)/hrs.length     : null;
  const bestPace = paces.length ? Math.min(...paces) : null;

  const cards = [
    {{ label:"Total Workouts", value: total, sub:"sessions logged" }},
    {{ label:"Total Distance", value: (totalDist/1000).toFixed(0)+" km", sub: totalDist.toLocaleString()+" m" }},
    {{ label:"Avg Pace",       value: avgPace  != null ? fmtPace(avgPace)  : "—", sub:"per 500 m" }},
    {{ label:"Best Pace",      value: bestPace != null ? fmtPace(bestPace) : "—", sub:"per 500 m" }},
    {{ label:"Avg Heart Rate", value: avgHR    != null ? Math.round(avgHR)+" bpm" : "—", sub:"across all sessions" }},
  ];
  document.getElementById("cards").innerHTML = cards.map(c => `
    <div class="card">
      <div class="card-label">${{c.label}}</div>
      <div class="card-value">${{c.value}}</div>
      <div class="card-sub">${{c.sub}}</div>
    </div>`).join("");
}}

// ── Chart ───────────────────────────────────────────────────────────────────
let chartInstance = null;

function paceLabel(sec) {{
  if (sec == null) return "";
  const m = Math.floor(sec/60), s = sec%60;
  return `${{m}}:${{s<10?'0':''}}${{s.toFixed(0)}}`;
}}

// Nice axis min/max around the data, padded and snapped to `step`.
function axisBounds(vals, pad, step) {{
  const nums = vals.filter(v => v != null);
  if (!nums.length) return {{ min: undefined, max: undefined }};
  const lo = Math.floor((Math.min(...nums) - pad) / step) * step;
  const hi = Math.ceil((Math.max(...nums) + pad) / step) * step;
  return {{ min: lo, max: hi }};
}}

// Least-squares linear fit of ys against xs; returns {{slope, intercept}} or null.
function linreg(xs, ys) {{
  const pts = [];
  ys.forEach((v, i) => {{ if (v != null && xs[i] != null) pts.push([xs[i], v]); }});
  if (pts.length < 2) return null;
  const n = pts.length;
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (const [x, y] of pts) {{ sx += x; sy += y; sxx += x*x; sxy += x*y; }}
  const denom = n*sxx - sx*sx;
  if (denom === 0) return null;
  const slope = (n*sxy - sx*sy) / denom;
  const intercept = (sy - slope*sx) / n;
  return {{ slope, intercept }};
}}

// First-degree fit over elapsed days; returns the two line endpoints (one straight
// segment across the full date range, no kinks), or null.
function trendLine(days, dates, vals) {{
  const fit = linreg(days, vals);
  if (!fit) return null;
  const last = days.length - 1;
  return [
    {{ x: dates[0],    y: fit.intercept + fit.slope * days[0] }},
    {{ x: dates[last], y: fit.intercept + fit.slope * days[last] }},
  ];
}}

// State for the main chart's selectable axes; metricByKey/METRICS are defined in
// the detail section but only referenced at runtime (after init), so this is safe.
let activeMainPrimary   = "pace";
let activeMainSecondary = "hr";   // "none" hides the secondary axis
let scopedData = [];              // latest date-filtered set, for control re-renders
let powerModel = "energy";        // "energy" = watt-min/time · "pace" = 2.80/v³

// Instantaneous-style power from a /500m pace via Concept2's cube law.
function paceToWatts(paceSec) {{
  if (paceSec == null || paceSec <= 0) return null;
  const spm = paceSec / 500;   // seconds per metre
  return Math.round(2.80 / (spm * spm * spm));
}}

// Resolve a metric's per-workout value, applying the chosen power model to the
// power-derived metrics (everything else reads its precomputed aggregate field).
function metricRowValue(r, m) {{
  if (powerModel === "pace") {{
    if (m.key === "watts") return paceToWatts(r.pace_sec);
    if (m.key === "wkg") {{
      const w = paceToWatts(r.pace_sec);
      return (w != null && WEIGHT_KG) ? Math.round(w / WEIGHT_KG * 100) / 100 : null;
    }}
  }}
  return r[m.row] ?? null;
}}

// Generic padded bounds (no metric-specific snapping).
function paddedBounds(vals) {{
  const nums = vals.filter(v => v != null);
  if (!nums.length) return {{ min: undefined, max: undefined }};
  const lo = Math.min(...nums), hi = Math.max(...nums);
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
  return {{ min: lo - pad, max: hi + pad }};
}}

function mainMetricsFor(data) {{
  return METRICS.filter(m => data.some(r => r[m.row] != null));
}}

function renderMainControls(data) {{
  const avail = mainMetricsFor(data);
  const keys = avail.map(m => m.key);
  if (!keys.includes(activeMainPrimary)) activeMainPrimary = keys[0] || "pace";
  if (activeMainSecondary !== "none" && !keys.includes(activeMainSecondary))
    activeMainSecondary = (keys.includes("hr") && activeMainPrimary !== "hr") ? "hr" : "none";
  const opts = sel => avail.map(m =>
    `<option value="${{m.key}}" ${{m.key === sel ? "selected" : ""}}>${{m.label}}</option>`).join("");
  document.getElementById("main-primary").innerHTML = opts(activeMainPrimary);
  document.getElementById("main-secondary").innerHTML =
    `<option value="none" ${{activeMainSecondary === "none" ? "selected" : ""}}>None</option>` + opts(activeMainSecondary);

  // The power model only matters when a power-derived metric is on an axis.
  document.getElementById("main-powermodel").value = powerModel;
  const powerShown = [activeMainPrimary, activeMainSecondary].some(k => k === "watts" || k === "wkg");
  document.getElementById("main-powermodel-label").classList.toggle("disabled", !powerShown);
}}

function trendDataset(label, pts, axis, color) {{
  return {{ label, data: pts, yAxisID: axis, borderColor: color + "80", borderDash: [6, 4],
           borderWidth: 1.5, pointRadius: 0, pointHitRadius: 0, tension: 0, fill: false }};
}}

function renderChart(data) {{
  const sorted = [...data].sort((a,b) => a.date < b.date ? -1 : (a.date > b.date ? 1 : 0));
  const labels = sorted.map(r => r.date.slice(0,10));

  const pm = metricByKey(activeMainPrimary) || METRICS[0];
  const secKey = (activeMainSecondary && activeMainSecondary !== "none" && activeMainSecondary !== activeMainPrimary)
    ? activeMainSecondary : null;
  const sm = secKey ? metricByKey(secKey) : null;

  const usesPower = [pm, sm].some(m => m && (m.key === "watts" || m.key === "wkg"));
  document.getElementById("main-chart-title").textContent =
    pm.label + (sm ? " & " + sm.label : "") + " across workouts" +
    (usesPower ? (powerModel === "pace" ? " · pace formula" : " · energy integral") : "");

  const pVals = sorted.map(r => metricRowValue(r, pm));
  const sVals = sm ? sorted.map(r => metricRowValue(r, sm)) : [];

  // Elapsed days from the first workout, so the trend reflects calendar time.
  const t0 = labels.length ? new Date(labels[0]).getTime() : 0;
  const days = labels.map(d => (new Date(d).getTime() - t0) / 86400000);
  const pTrend = trendLine(days, labels, pVals);
  const sTrend = sm ? trendLine(days, labels, sVals) : null;

  const tickCb = m => (val => m.key === "pace" ? paceLabel(val) : Math.round(val * 100) / 100);

  const datasets = [{{
    label: pm.label,
    data: pVals,
    yAxisID: "y",
    borderColor: pm.color,
    backgroundColor: pm.color + "14",
    borderWidth: 2.5,
    pointRadius: 4,
    pointBackgroundColor: pm.color,
    pointHoverRadius: 6,
    tension: 0.35,
    fill: !sm,
    spanGaps: true,
  }}];
  if (pTrend) datasets.push(trendDataset(pm.label + " trend", pTrend, "y", pm.color));

  if (sm) {{
    datasets.push({{
      label: sm.label,
      data: sVals,
      yAxisID: "y2",
      borderColor: sm.color,
      backgroundColor: sm.color + "10",
      borderWidth: 2.5,
      pointRadius: 4,
      pointBackgroundColor: sm.color,
      pointHoverRadius: 6,
      tension: 0.35,
      fill: false,
      spanGaps: true,
    }});
    if (sTrend) datasets.push(trendDataset(sm.label + " trend", sTrend, "y2", sm.color));
  }}

  const pB = paddedBounds(pVals), sB = sm ? paddedBounds(sVals) : null;
  const scales = {{
    x: {{
      type: "time",
      time: {{ unit: "day", displayFormats: {{ day: "dd MMM" }} }},
      grid: {{ display: false }},
      ticks: {{ maxTicksLimit: 12, font: {{ size: 11 }} }}
    }},
    y: {{
      type: "linear", position: "left", reverse: !!pm.reverse, min: pB.min, max: pB.max,
      title: {{ display: true, text: pm.label, color: pm.color, font: {{ size: 11 }} }},
      ticks: {{ font: {{ size: 11 }}, color: pm.color, callback: tickCb(pm) }},
      grid: {{ color: "rgba(0,0,0,.05)" }}
    }}
  }};
  if (sm) scales.y2 = {{
    type: "linear", position: "right", reverse: !!sm.reverse, min: sB.min, max: sB.max,
    title: {{ display: true, text: sm.label, color: sm.color, font: {{ size: 11 }} }},
    ticks: {{ font: {{ size: 11 }}, color: sm.color, callback: tickCb(sm) }},
    grid: {{ drawOnChartArea: false }}
  }};

  if (chartInstance) chartInstance.destroy();
  chartInstance = new Chart(document.getElementById("chart"), {{
    type: "line",
    data: {{ labels, datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{
        legend: {{ position: "top", labels: {{ usePointStyle: true, padding: 20, font: {{ size: 12 }} }} }},
        tooltip: {{
          filter(ctx) {{ return !ctx.dataset.label.includes("trend"); }},
          callbacks: {{
            label(ctx) {{
              if (ctx.raw == null) return null;
              const m = ctx.dataset.yAxisID === "y2" ? sm : pm;
              return ` ${{ctx.dataset.label}}: ${{m.fmt(ctx.raw)}}`;
            }}
          }}
        }}
      }},
      scales
    }}
  }});
}}

// ── Effort-quality small multiples (one value per workout, over time) ─────────
const EFFORT_TRENDS = [
  {{ key:"pacecv",   metric:"pace_cv",    color:"#0d9488", reverse:true,  fmt:v => v.toFixed(1)+"%" }},
  {{ key:"spmcv",    metric:"spm_cv",     color:"#65a30d", reverse:true,  fmt:v => v.toFixed(1)+"%" }},
  {{ key:"pacefade", metric:"pace_fade",  color:"#c026d3", reverse:false, fmt:v => (v>=0?"+":"")+v.toFixed(1)+"%" }},
  {{ key:"decouple", metric:"decoupling", color:"#dc2626", reverse:false, fmt:v => (v>=0?"+":"")+v.toFixed(1)+"%" }},
];
let effortTrendCharts = {{}};

function renderEffortTrends(data) {{
  const sorted = [...data].sort((a,b) => a.date < b.date ? -1 : (a.date > b.date ? 1 : 0));
  const labels = sorted.map(r => r.date.slice(0,10));
  const t0 = labels.length ? new Date(labels[0]).getTime() : 0;
  const days = labels.map(d => (new Date(d).getTime() - t0) / 86400000);

  const anyData = EFFORT_TRENDS.some(et => sorted.some(r => r[et.metric] != null));
  document.getElementById("effort-trend-grid").style.display = anyData ? "" : "none";
  document.getElementById("effort-trend-empty").style.display = anyData ? "none" : "";

  EFFORT_TRENDS.forEach(et => {{
    const vals = sorted.map(r => r[et.metric] ?? null);
    const latest = [...vals].reverse().find(v => v != null);
    document.getElementById("et-" + et.key + "-latest").textContent = latest != null ? et.fmt(latest) : "—";

    const trend  = trendLine(days, labels, vals);
    const bounds = paddedBounds(vals);
    const datasets = [{{
      data: vals, borderColor: et.color, backgroundColor: et.color + "14",
      borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: et.color, pointHoverRadius: 5,
      tension: 0.3, fill: true, spanGaps: true,
    }}];
    if (trend) datasets.push({{
      data: trend, borderColor: et.color + "80", borderDash: [5,4],
      borderWidth: 1.5, pointRadius: 0, pointHitRadius: 0, fill: false,
    }});

    if (effortTrendCharts[et.key]) effortTrendCharts[et.key].destroy();
    effortTrendCharts[et.key] = new Chart(document.getElementById("et-" + et.key), {{
      type: "line",
      data: {{ labels, datasets }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: "index", intersect: false }},
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{ filter: ctx => ctx.datasetIndex === 0,
                      callbacks: {{ label: ctx => ctx.raw == null ? null : " " + et.fmt(ctx.raw) }} }}
        }},
        scales: {{
          x: {{ type: "time", time: {{ unit: "day", displayFormats: {{ day: "dd MMM" }} }},
                grid: {{ display: false }}, ticks: {{ maxTicksLimit: 6, font: {{ size: 10 }} }} }},
          y: {{ reverse: et.reverse, min: bounds.min, max: bounds.max,
                ticks: {{ font: {{ size: 10 }}, color: et.color, callback: v => Math.round(v*10)/10 }},
                grid: {{ color: "rgba(0,0,0,.05)" }} }}
        }}
      }}
    }});
  }});
}}

// ── Table ───────────────────────────────────────────────────────────────────
const PAGE = 20;
let tableData = [];
let sortCol   = "date";
let sortAsc   = false;
let page      = 1;

function hrClass(hr) {{
  if (!hr) return "hr-na";
  if (hr < 120) return "hr-z1";
  if (hr < 140) return "hr-z2";
  return "hr-z3";
}}

function fmtDate(s) {{
  const d = new Date(s.replace(" ", "T"));
  return d.toLocaleDateString("en-GB", {{day:"2-digit",month:"short",year:"numeric"}})
    + " " + d.toLocaleTimeString("en-GB", {{hour:"2-digit",minute:"2-digit"}});
}}

function renderRows() {{
  const total = tableData.length;
  const totalPages = Math.max(1, Math.ceil(total/PAGE));
  if (page > totalPages) page = totalPages;
  if (page < 1) page = 1;
  const start = (page-1)*PAGE, end = start+PAGE;
  const slice = tableData.slice(start, end);
  document.getElementById("tbody").innerHTML = slice.map(r => `
    <tr class="clickable" data-id="${{r.id}}">
      <td>${{fmtDate(r.date)}} <span class="row-chevron">›</span></td>
      <td><strong>${{(r.distance/1000).toFixed(2)}} km</strong> <span style="color:#aaa;font-size:.8rem">(${{r.distance.toLocaleString()}} m)</span></td>
      <td>${{r.duration}}</td>
      <td>${{r.pace_fmt}}</td>
      <td><span class="hr-pill ${{hrClass(r.avg_hr)}}">${{r.avg_hr != null ? r.avg_hr+" bpm" : "—"}}</span></td>
      <td>${{r.calories != null ? r.calories+" kcal" : "—"}}</td>
      <td>${{r.stroke_rate != null ? r.stroke_rate+" spm" : "—"}}</td>
    </tr>`).join("");

  document.getElementById("page-info").textContent =
    total ? `${{Math.min(start+1,total)}}–${{Math.min(end,total)}} of ${{total}}` : "0 of 0";
  document.getElementById("prev-btn").disabled = page <= 1;
  document.getElementById("next-btn").disabled = page >= totalPages;
  document.getElementById("count-label").textContent =
    total < DATA.length ? `(${{total}} of ${{DATA.length}})` : `(${{DATA.length}})`;
}}

function applySort() {{
  tableData.sort((a,b) => {{
    let av = a[sortCol], bv = b[sortCol];
    if (av == null) av = sortAsc ? Infinity : -Infinity;
    if (bv == null) bv = sortAsc ? Infinity : -Infinity;
    if (typeof av === "string") return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortAsc ? av - bv : bv - av;
  }});
  document.querySelectorAll("thead th[data-col]").forEach(th => {{
    const c = th.dataset.col;
    th.classList.toggle("sorted", c === sortCol);
    const icon = th.querySelector(".sort-icon");
    if (icon) icon.textContent = c === sortCol ? (sortAsc ? "↑" : "↓") : "↕";
  }});
  renderRows();
}}

function sortBy(col) {{
  if (sortCol === col) {{ sortAsc = !sortAsc; }}
  else {{ sortCol = col; sortAsc = col !== "date"; }}
  page = 1;
  applySort();
}}

// ── Single-workout detail view ────────────────────────────────────────────────
// Canonical metrics, shared by the per-stroke and per-split charts. `split`
// names the per-split field; per-stroke values are computed in strokeSeries().
const WEIGHT_KG = PROFILE.weight_kg || null;
const HR_MAX    = PROFILE.max_heart_rate || null;

// `split` = per-split field (detail chart); `row` = per-workout aggregate field
// (main dashboard chart). See aggregate_metrics() in build_dashboard.py.
const METRICS = [
  {{ key:"pace",  label:"Pace",            color:"#2563eb", reverse:true,  split:"pace_sec",    row:"pace_sec",    fmt:v => paceLabel(v)+"/500m" }},
  {{ key:"hr",    label:"Heart Rate",      color:"#e94560", reverse:false, split:"hr_avg",      row:"avg_hr",      fmt:v => Math.round(v)+" bpm" }},
  {{ key:"hrpct", label:"% Max HR",        color:"#db2777", reverse:false, split:null,          row:"hrpct",       fmt:v => Math.round(v)+"%" }},
  {{ key:"spm",   label:"Stroke Rate",     color:"#16a34a", reverse:false, split:"stroke_rate", row:"stroke_rate", fmt:v => v+" spm" }},
  {{ key:"dps",   label:"Meters / Stroke", color:"#0891b2", reverse:false, split:null,          row:"dps",         fmt:v => v.toFixed(1)+" m" }},
  {{ key:"watts", label:"Power",           color:"#9333ea", reverse:false, split:"watts",       row:"watts",       fmt:v => Math.round(v)+" W" }},
  {{ key:"wkg",   label:"Watts / kg",      color:"#7c3aed", reverse:false, split:null,          row:"wkg",         fmt:v => v.toFixed(2)+" W/kg" }},
  {{ key:"work",  label:"Work / Stroke",   color:"#ca8a04", reverse:false, split:null,          row:"work",        fmt:v => Math.round(v)+" J" }},
  {{ key:"calhr", label:"Calories / hr",   color:"#f59e0b", reverse:false, split:null,          row:"calhr",       fmt:v => Math.round(v)+" cal/hr" }},
  {{ key:"cal",   label:"Calories",        color:"#ea580c", reverse:false, split:"calories",    row:"calories",    fmt:v => v+" kcal" }},
  {{ key:"pacecv",   label:"Pace consistency",       color:"#0d9488", reverse:true,  split:null, row:"pace_cv",    fmt:v => v.toFixed(1)+"% CV" }},
  {{ key:"spmcv",    label:"Stroke-rate consistency",color:"#65a30d", reverse:true,  split:null, row:"spm_cv",     fmt:v => v.toFixed(1)+"% CV" }},
  {{ key:"pacefade", label:"Pace fade",              color:"#c026d3", reverse:false, split:null, row:"pace_fade",  fmt:v => (v>=0?"+":"")+v.toFixed(1)+"%" }},
  {{ key:"decouple", label:"Aerobic decoupling",     color:"#dc2626", reverse:false, split:null, row:"decoupling", fmt:v => (v>=0?"+":"")+v.toFixed(1)+"%" }},
];

// Instantaneous power (watts) for stroke i from pace p (tenths s / 500 m).
function strokeWatts(p) {{
  const mps = p > 0 ? (p / 10) / 500 : 0;   // seconds per metre
  return mps > 0 ? 2.80 / (mps * mps * mps) : null;
}}
let detailChartInstance = null;
let activePrimary   = "pace";
let activeSecondary = "hr";    // "" / "none" means no secondary axis
let showSplits      = false;

const metricByKey = k => METRICS.find(m => m.key === k);

function fmtClock(sec) {{
  const m = Math.floor(sec/60), s = Math.round(sec%60);
  return `${{m}}:${{s<10?'0':''}}${{s}}`;
}}

function hasStrokes(d) {{
  const s = STROKES[String(d.id)];
  return !!(s && s.t && s.t.length);
}}

// Build a per-stroke series for a canonical metric as [{{x: seconds, y}}].
// p is tenths of a second per 500 m; power uses Concept2's 2.80 / (s/m)^3.
function strokeSeries(s, key) {{
  const n = s.t.length, out = new Array(n);
  for (let i = 0; i < n; i++) {{
    const x = s.t[i] / 10;
    let y = null;
    if      (key === "pace")  {{ const p = s.p[i]; y = p > 0 ? p / 10 : null; }}
    else if (key === "hr")    {{ y = s.hr[i]  || null; }}
    else if (key === "hrpct") {{ y = (HR_MAX && s.hr[i]) ? (s.hr[i] / HR_MAX) * 100 : null; }}
    else if (key === "spm")   {{ y = s.spm[i] != null ? s.spm[i] : null; }}
    else if (key === "dps")   {{ // metres gained this stroke (d is tenths of a metre)
                                 const dm = i === 0 ? null : (s.d[i] - s.d[i-1]) / 10;
                                 y = (dm != null && dm >= 0) ? dm : null; }}
    else if (key === "watts") {{ y = strokeWatts(s.p[i]); }}
    else if (key === "wkg")   {{ const w = strokeWatts(s.p[i]); y = (WEIGHT_KG && w != null) ? w / WEIGHT_KG : null; }}
    else if (key === "calhr") {{ const w = strokeWatts(s.p[i]); y = w != null ? w * 3.4416 + 300 : null; }}
    else if (key === "work")  {{ // joules this stroke = power × stroke duration
                                 const w = strokeWatts(s.p[i]);
                                 const dt = i === 0 ? null : (s.t[i] - s.t[i-1]) / 10;
                                 y = (w != null && dt != null && dt > 0) ? w * dt : null; }}
    out[i] = {{ x, y }};
  }}
  return out;
}}

// Which metrics have data for this workout (drives the axis selectors).
function metricsFor(d) {{
  if (hasStrokes(d)) {{
    const s = STROKES[String(d.id)];
    return METRICS.filter(m => m.key !== "cal" && strokeSeries(s, m.key).some(pt => pt.y != null));
  }}
  return METRICS.filter(m => d.splits.some(sp => sp[m.split] != null));
}}

// Per-split average of a stroke metric, drawn as a staircase over the trace:
// two points per split (start & end of its time window) at the split's mean.
function splitAvgSeries(d, key) {{
  const s = STROKES[String(d.id)];
  if (!s || !d.splits.length) return [];
  const series = strokeSeries(s, key);
  const out = [];
  let start = 0;
  for (const sp of d.splits) {{
    const end = sp.cum_time_sec;
    const ys = series.filter(pt => pt.x > start && pt.x <= end && pt.y != null).map(pt => pt.y);
    if (ys.length) {{
      const mean = ys.reduce((a, b) => a + b, 0) / ys.length;
      out.push({{ x: start, y: mean }}, {{ x: end, y: mean }});
    }}
    start = end;
  }}
  return out;
}}

function renderDetailCards(d) {{
  const avgPower = powerModel === "pace" ? paceToWatts(d.pace_sec) : d.avg_watts;
  const powerSub = powerModel === "pace" ? "watts · pace formula"
                 : (d.watts_est ? "watts · estimated from strokes" : "watts · energy integral");
  const cards = [
    {{ label:"Distance",     value:(d.distance/1000).toFixed(2)+" km", sub:d.distance.toLocaleString()+" m" }},
    {{ label:"Duration",     value:d.duration, sub:"total time" }},
    {{ label:"Avg Pace",     value:d.pace_sec!=null?fmtPace(d.pace_sec):"—", sub:"per 500 m" }},
    {{ label:"Avg Power",    value:avgPower!=null?avgPower+" W":"—", sub:powerSub }},
    {{ label:"Avg HR",       value:d.avg_hr!=null?d.avg_hr+" bpm":"—", sub:d.max_hr!=null?("max "+d.max_hr+" bpm"):"heart rate" }},
    {{ label:"Calories",     value:d.calories!=null?d.calories+" kcal":"—", sub:"total burned" }},
    {{ label:"Avg Stroke Rate", value:d.stroke_rate!=null?d.stroke_rate+" spm":"—", sub:d.stroke_count!=null?(d.stroke_count+" strokes"):"strokes/min" }},
    {{ label:"Drag Factor",  value:d.drag_factor!=null?d.drag_factor:"—", sub:"flywheel setting" }},
  ];
  document.getElementById("d-cards").innerHTML = cards.map(c => `
    <div class="card">
      <div class="card-label">${{c.label}}</div>
      <div class="card-value">${{c.value}}</div>
      <div class="card-sub">${{c.sub}}</div>
    </div>`).join("");
}}

function renderSplitsTable(d) {{
  const sp = d.splits;
  document.getElementById("d-split-count").textContent = sp.length ? `(${{sp.length}})` : "";
  if (!sp.length) {{
    document.getElementById("d-splits-body").innerHTML =
      `<div class="splits-note">No per-split data was recorded for this workout.</div>`;
    return;
  }}
  const body = sp.map(s => `
    <tr>
      <td class="num">${{s.idx}}</td>
      <td>${{s.duration}}</td>
      <td class="num">${{s.distance.toLocaleString()}} m</td>
      <td>${{s.pace_fmt}}</td>
      <td class="num">${{s.stroke_rate!=null?s.stroke_rate+" spm":"—"}}</td>
      <td class="num">${{s.watts!=null?s.watts+" W":"—"}}</td>
      <td class="num">${{s.calories!=null?s.calories+" kcal":"—"}}</td>
      <td class="num"><span class="hr-pill ${{hrClass(s.hr_avg)}}">${{s.hr_avg!=null?s.hr_avg+" bpm":"—"}}</span></td>
      <td class="num">${{s.hr_max!=null?s.hr_max+" bpm":"—"}}</td>
    </tr>`).join("");
  document.getElementById("d-splits-body").innerHTML = `
    <table>
      <thead><tr>
        <th class="num">#</th><th>Time</th><th class="num">Distance</th><th>Pace</th>
        <th class="num">Stroke Rate</th><th class="num">Power</th><th class="num">Calories</th>
        <th class="num">Avg HR</th><th class="num">Max HR</th>
      </tr></thead>
      <tbody>${{body}}</tbody>
    </table>`;
}}

function renderChartControls(d) {{
  const avail = metricsFor(d);
  const keys = avail.map(m => m.key);
  // Keep current selections if still valid, else fall back sensibly.
  if (!keys.includes(activePrimary)) activePrimary = keys[0] || "pace";
  if (activeSecondary && activeSecondary !== "none" && !keys.includes(activeSecondary)) {{
    activeSecondary = keys.includes("hr") && "hr" !== activePrimary ? "hr" : "none";
  }}

  const opts = sel => avail.map(m =>
    `<option value="${{m.key}}" ${{m.key === sel ? "selected" : ""}}>${{m.label}}</option>`).join("");

  document.getElementById("d-primary").innerHTML = opts(activePrimary);
  document.getElementById("d-secondary").innerHTML =
    `<option value="none" ${{(!activeSecondary || activeSecondary === "none") ? "selected" : ""}}>None</option>` + opts(activeSecondary);

  // Split-average overlay only applies to the per-stroke chart.
  const splitsOk = hasStrokes(d);
  const cb = document.getElementById("d-show-splits");
  cb.checked = splitsOk && showSplits;
  cb.disabled = !splitsOk;
  document.getElementById("d-splits-label").classList.toggle("disabled", !splitsOk);
}}

// Dispatcher: per-stroke time series when available, else per-split fallback.
function renderDetailChart(d) {{
  if (detailChartInstance) {{ detailChartInstance.destroy(); detailChartInstance = null; }}
  const titleEl = document.getElementById("d-chart-title");
  if (hasStrokes(d)) {{
    titleEl.textContent = "Metrics over time (per stroke)";
    renderStrokeChart(d);
  }} else {{
    titleEl.textContent = "Metrics per split";
    renderSplitChart(d);
  }}
}}

// One datapoint per stroke; x-axis is elapsed time in seconds. The primary and
// secondary metrics are user-selected; an optional split-average staircase
// overlays the primary metric.
function renderStrokeChart(d) {{
  const s = STROKES[String(d.id)];
  const primary = metricByKey(activePrimary) || METRICS[0];
  const secKey = (activeSecondary && activeSecondary !== "none" && activeSecondary !== activePrimary)
    ? activeSecondary : null;
  const secondary = secKey ? metricByKey(secKey) : null;

  const main = strokeSeries(s, primary.key);
  const datasets = [{{
    label: primary.label,
    data: main,
    yAxisID: "y",
    borderColor: primary.color,
    backgroundColor: primary.color + "14",
    borderWidth: 1.6,
    pointRadius: 0,
    pointHoverRadius: 4,
    tension: 0.2,
    fill: !secondary,   // only fill when it's the sole trace, to keep it readable
    spanGaps: true,
  }}];

  if (secondary) datasets.push({{
    label: secondary.label,
    data: strokeSeries(s, secondary.key),
    yAxisID: "y2",
    borderColor: secondary.color,
    borderWidth: 1.3,
    pointRadius: 0,
    pointHoverRadius: 4,
    tension: 0.2,
    fill: false,
    spanGaps: true,
  }});

  if (showSplits) {{
    const ov = splitAvgSeries(d, primary.key);
    if (ov.length) datasets.push({{
      label: primary.label + " (split avg)",
      data: ov,
      yAxisID: "y",
      borderColor: primary.color,
      borderWidth: 2.6,
      borderDash: [7, 3],
      pointRadius: 0,
      pointHoverRadius: 0,
      tension: 0,
      fill: false,
      spanGaps: false,
    }});
  }}

  const maxX = main.length ? main[main.length - 1].x : 0;
  const tickCb = m => (v => m.key === "pace" ? fmtClock(v) : Math.round(v));
  const scales = {{
    x: {{
      type: "linear", min: 0, max: maxX,
      title: {{ display: true, text: "Elapsed time", font: {{ size: 11 }} }},
      ticks: {{ font: {{ size: 11 }}, maxTicksLimit: 12, callback: v => fmtClock(v) }},
      grid: {{ display: false }}
    }},
    y: {{
      type: "linear", position: "left", reverse: !!primary.reverse,
      title: {{ display: true, text: primary.label, color: primary.color, font: {{ size: 11 }} }},
      ticks: {{ font: {{ size: 11 }}, color: primary.color, callback: tickCb(primary) }},
      grid: {{ color: "rgba(0,0,0,.05)" }}
    }}
  }};
  if (secondary) scales.y2 = {{
    type: "linear", position: "right", reverse: !!secondary.reverse,
    title: {{ display: true, text: secondary.label, color: secondary.color, font: {{ size: 11 }} }},
    ticks: {{ font: {{ size: 11 }}, color: secondary.color, callback: tickCb(secondary) }},
    grid: {{ drawOnChartArea: false }}
  }};

  detailChartInstance = new Chart(document.getElementById("d-chart"), {{
    type: "line",
    data: {{ datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      normalized: true,
      interaction: {{ mode: "nearest", axis: "x", intersect: false }},
      plugins: {{
        legend: {{ position: "top", labels: {{ usePointStyle: true, padding: 18, font: {{ size: 12 }} }} }},
        decimation: {{ enabled: true, algorithm: "lttb", samples: 700 }},
        tooltip: {{
          callbacks: {{
            title(items) {{ return "Time " + fmtClock(items[0].parsed.x); }},
            label(ctx) {{
              if (ctx.parsed.y == null) return null;
              const m = ctx.dataset.yAxisID === "y2" ? secondary : primary;
              return ` ${{ctx.dataset.label}}: ${{m.fmt(ctx.parsed.y)}}`;
            }}
          }}
        }}
      }},
      scales
    }}
  }});
}}

// Fallback for workouts without stroke data: one datapoint per split.
function renderSplitChart(d) {{
  const sp = d.splits;
  if (!sp.length) return;
  const primary = metricByKey(activePrimary) || METRICS[0];
  const secKey = (activeSecondary && activeSecondary !== "none" && activeSecondary !== activePrimary)
    ? activeSecondary : null;
  const secondary = secKey ? metricByKey(secKey) : null;
  const labels = sp.map(s => "Split " + s.idx);

  const datasets = [{{
    label: primary.label,
    data: sp.map(s => s[primary.split]),
    yAxisID: "y",
    borderColor: primary.color,
    backgroundColor: primary.color + "1a",
    borderWidth: 2.5,
    pointRadius: 3,
    pointHoverRadius: 6,
    tension: 0.3,
    fill: !secondary,
    spanGaps: true,
  }}];

  if (secondary) datasets.push({{
    label: secondary.label,
    data: sp.map(s => s[secondary.split]),
    yAxisID: "y2",
    borderColor: secondary.color,
    borderWidth: 1.5,
    borderDash: [5, 4],
    pointRadius: 0,
    pointHoverRadius: 5,
    tension: 0.3,
    fill: false,
    spanGaps: true,
  }});

  const tickCb = m => (v => m.key === "pace" ? fmtClock(v) : v);
  const scales = {{
    x: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
    y: {{
      type: "linear", position: "left", reverse: !!primary.reverse,
      title: {{ display: true, text: primary.label, color: primary.color, font: {{ size: 11 }} }},
      ticks: {{ font: {{ size: 11 }}, color: primary.color, callback: tickCb(primary) }},
      grid: {{ color: "rgba(0,0,0,.05)" }}
    }}
  }};
  if (secondary) scales.y2 = {{
    type: "linear", position: "right", reverse: !!secondary.reverse,
    title: {{ display: true, text: secondary.label, color: secondary.color, font: {{ size: 11 }} }},
    ticks: {{ font: {{ size: 11 }}, color: secondary.color, callback: tickCb(secondary) }},
    grid: {{ drawOnChartArea: false }}
  }};

  detailChartInstance = new Chart(document.getElementById("d-chart"), {{
    type: "line",
    data: {{ labels, datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{
        legend: {{ position: "top", labels: {{ usePointStyle: true, padding: 18, font: {{ size: 12 }} }} }},
        tooltip: {{
          callbacks: {{
            title(items) {{
              const s = sp[items[0].dataIndex];
              return `Split ${{s.idx}} · ${{s.distance.toLocaleString()}} m @ ${{fmtClock(s.cum_time_sec)}}`;
            }},
            label(ctx) {{
              if (ctx.raw == null) return null;
              const m = ctx.dataset.yAxisID === "y2" ? secondary : primary;
              return ` ${{ctx.dataset.label}}: ${{m.fmt(ctx.raw)}}`;
            }}
          }}
        }}
      }},
      scales
    }}
  }});
}}

// ── Effort & quality ──────────────────────────────────────────────────────────
// Mean and (population) std-dev of the non-null numbers in an array.
function meanStd(arr) {{
  const v = arr.filter(x => x != null && !isNaN(x));
  if (!v.length) return null;
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - mean) * (b - mean), 0) / v.length);
  return {{ mean, sd, n: v.length }};
}}

// Parallel per-stroke (or per-split fallback) series used by the effort stats.
function effortSeries(d) {{
  const t = [], power = [], hr = [], pace = [], spm = [];
  if (hasStrokes(d)) {{
    const s = STROKES[String(d.id)];
    for (let i = 0; i < s.t.length; i++) {{
      t.push(s.t[i] / 10);
      power.push(strokeWatts(s.p[i]));
      hr.push(s.hr[i] || null);
      pace.push(s.p[i] > 0 ? s.p[i] / 10 : null);
      spm.push(s.spm[i] || null);
    }}
  }} else {{
    let acc = 0;
    d.splits.forEach(s => {{
      acc += s.time / 10;
      t.push(acc); power.push(s.watts || null); hr.push(s.hr_avg || null);
      pace.push(s.pace_sec || null); spm.push(s.stroke_rate || null);
    }});
  }}
  return {{ t, power, hr, pace, spm, total: t.length ? t[t.length - 1] : 0 }};
}}

function renderEffortCards(d) {{
  const e = effortSeries(d);
  const cards = [];

  const pc = meanStd(e.pace);
  if (pc && pc.mean) cards.push({{ label:"Pace consistency", value:(pc.sd / pc.mean * 100).toFixed(1) + "%", sub:"CV — lower is steadier" }});
  const sc = meanStd(e.spm);
  if (sc && sc.mean) cards.push({{ label:"Stroke-rate consistency", value:(sc.sd / sc.mean * 100).toFixed(1) + "%", sub:"CV of stroke rate" }});

  // Split the piece at its time midpoint for fade / decoupling.
  const mid = e.total / 2;
  const firstPace = [], secondPace = [], firstEF = [], secondEF = [];
  for (let i = 0; i < e.t.length; i++) {{
    const first = e.t[i] <= mid;
    if (e.pace[i] != null) (first ? firstPace : secondPace).push(e.pace[i]);
    if (e.power[i] != null && e.hr[i] > 0) (first ? firstEF : secondEF).push(e.power[i] / e.hr[i]);
  }}
  const fp = meanStd(firstPace), spc = meanStd(secondPace);
  if (fp && spc && fp.mean) {{
    const diff = spc.mean - fp.mean, pct = diff / fp.mean * 100;
    cards.push({{ label:"Pace fade", value:(diff >= 0 ? "+" : "") + diff.toFixed(1) + " s",
                  sub:`2nd vs 1st half · ${{(pct >= 0 ? "+" : "") + pct.toFixed(1)}}%` }});
  }}
  const f1 = meanStd(firstEF), f2 = meanStd(secondEF);
  if (f1 && f2 && f1.mean) {{
    const dec = (f1.mean - f2.mean) / f1.mean * 100;
    cards.push({{ label:"Aerobic decoupling", value:(dec >= 0 ? "+" : "") + dec.toFixed(1) + "%",
                  sub:"Pw:Hr drift · <5% strong base" }});
  }}

  document.getElementById("d-effort-cards").innerHTML = cards.length
    ? cards.map(c => `<div class="card"><div class="card-label">${{c.label}}</div><div class="card-value">${{c.value}}</div><div class="card-sub">${{c.sub}}</div></div>`).join("")
    : `<div class="splits-note">Not enough data to compute effort metrics.</div>`;
}}

// ── Projected race times (Riegel: t₂ = t₁·(d₂/d₁)^1.06) ────────────────────────
function renderProjCards(d) {{
  const d1 = d.distance, t1 = d.time / 10;  // metres, seconds
  const host = document.getElementById("d-proj-cards");
  if (!d1 || !t1) {{ host.innerHTML = `<div class="splits-note">No distance/time to project from.</div>`; return; }}
  const cards = RANK_TARGETS.map(tg => {{
    if (tg.t === "dist") {{
      const t2 = t1 * Math.pow(tg.m / d1, RIEGEL_R);
      return {{ label:tg.l, value:clockHMS(t2), sub:projSub(tg.m / t2) }};
    }}
    const d2 = d1 * Math.pow(tg.s / t1, 1 / RIEGEL_R);
    return {{ label:tg.l, value:Math.round(d2).toLocaleString() + " m", sub:projSub(d2 / tg.s) }};
  }});
  host.innerHTML = cards.map(c =>
    `<div class="card"><div class="card-label">${{c.label}}</div><div class="card-value">${{c.value}}</div><div class="card-sub">${{c.sub}}</div></div>`).join("");
}}

// ── Power curve (mean-maximal power) + global projections ─────────────────────
// Durations (seconds) sampled along the curve; only those reachable by at least
// one filtered workout are drawn. Sampling granularity tightens at shorter
// durations: 10 s below 5 min, 15 s below 10 min, 30 s below 30 min, 1 min
// below 60 min, then 5 min beyond an hour.
const PC_DURATIONS = (() => {{
  const out = [];
  const add = (from, to, step) => {{ for (let s = from; s < to; s += step) out.push(s); }};
  add(10,   300,   10);    // < 5 min  → 10 s
  add(300,  600,   15);    // < 10 min → 15 s
  add(600,  1800,  30);    // < 30 min → 30 s
  add(1800, 3600,  60);    // < 60 min → 1 min
  add(3600, 14401, 300);   // ≥ 60 min → 5 min (cap 4 h)
  return out;
}})();
let pcChartInstance = null;
let pcAnchorMode = "best";   // "best" across anchors · "nearest" duration anchor
let pcLastCurve = null;      // latest computed curve, for re-projecting on toggle

// Cumulative (elapsed-seconds, work-joules) series for one workout. Prefers
// per-stroke pace samples (cube-law watts, self-calibrated); falls back to the
// per-split average-watt series. Returns null when neither is available.
function workoutWorkSeries(id) {{
  const s = STROKES[String(id)];
  if (s && s.t && s.t.length > 1) {{
    const t = s.t, p = s.p || [];
    const T = [0], W = [0];
    let cum = 0, prev = 0;
    for (let i = 0; i < t.length; i++) {{
      const dt = (t[i] - prev) / 10;          // tenths -> seconds
      prev = t[i];
      const pv = p[i];
      if (pv > 0 && dt > 0) {{
        const secPerM = pv / 5000;            // tenths-sec/500m -> sec/m
        cum += (2.80 / (secPerM ** 3)) * WATTMIN_CAL * dt;
      }}
      T.push(t[i] / 10);
      W.push(cum);
    }}
    return {{ T, W }};
  }}
  const d = DETAIL[String(id)];
  if (d && d.splits && d.splits.length) {{
    const T = [0], W = [0];
    let cum = 0, acc = 0;
    for (const sp of d.splits) {{
      const dt = (sp.time || 0) / 10;
      acc += dt;
      cum += (sp.watts || 0) * dt;            // split watts are already calibrated
      T.push(acc);
      W.push(cum);
    }}
    return {{ T, W }};
  }}
  return null;
}}

// Best average power (W) over every window of length >= each PC_DURATIONS entry,
// for a single workout. Returns an array parallel to PC_DURATIONS.
//
// A power-duration curve must be non-increasing: any window that holds P watts
// for L seconds also holds >= P watts over any shorter span inside it. We get
// this exactly by assigning each window to the largest grid bucket <= its
// length, keeping the best average per bucket, then sweeping long -> short so a
// strong long effort floors every shorter duration. (The old code averaged only
// the *smallest* window >= D from each start, which let a longer target pick a
// higher-average window and made the curve rise — the reported artefact.)
function workoutMMP(series) {{
  const T = series.T, W = series.W, n = T.length;
  const G = PC_DURATIONS, ng = G.length;
  const res = new Array(ng).fill(0);
  if (n < 2 || T[n-1] < G[0]) return res;
  for (let i = 0; i < n - 1; i++) {{
    if (T[n-1] - T[i] < G[0]) break;            // no window from here reaches G[0]
    let g = 0;                                  // length grows with j, so g only rises
    for (let j = i + 1; j < n; j++) {{
      const L = T[j] - T[i];
      if (L < G[0]) continue;
      while (g + 1 < ng && G[g + 1] <= L) g++;
      const A = (W[j] - W[i]) / L;
      if (A > res[g]) res[g] = A;
    }}
  }}
  for (let k = ng - 2; k >= 0; k--) if (res[k + 1] > res[k]) res[k] = res[k + 1];
  return res;
}}

// Pointwise best across all filtered workouts. The max of non-increasing curves
// is itself non-increasing, so the aggregate stays monotonic.
function powerCurveFromSeries(series) {{
  const G = PC_DURATIONS;
  const agg = new Array(G.length).fill(0);
  const src = new Array(G.length).fill(null);
  for (const it of series) {{
    const mmp = workoutMMP(it.s);
    for (let k = 0; k < G.length; k++) {{
      if (mmp[k] > agg[k]) {{ agg[k] = mmp[k]; src[k] = it; }}
    }}
  }}
  const curve = [];
  for (let k = 0; k < G.length; k++) {{
    if (agg[k] > 0) curve.push({{
      D: G[k], p: agg[k],
      srcId: src[k] ? src[k].id : null,
      srcDate: src[k] ? src[k].date : null,
    }});
  }}
  return curve;
}}

// Riegel-project every ranked target from the power curve, anchoring only on
// efforts of >= 5 min. Two modes:
//   "best"    — keep the strongest projection across all eligible efforts.
//   "nearest" — project from the single effort closest (in log space) to the
//               target, by distance for distance targets and by duration for
//               time targets. Minimises how far Riegel has to extrapolate.
function projectFromCurve(curve, mode) {{
  const anchors = curve
    .filter(c => c.D >= 300)
    .map(c => ({{ d: Math.cbrt(c.p / 2.80) * c.D, t: c.D }}));  // cube-law speed * time
  if (!anchors.length) return null;
  const nearestBy = (key, target) => anchors.reduce((best, a) =>
    Math.abs(Math.log(a[key] / target)) < Math.abs(Math.log(best[key] / target)) ? a : best);
  return RANK_TARGETS.map(tg => {{
    if (tg.t === "dist") {{
      let t2;
      if (mode === "nearest") {{
        const a = nearestBy("d", tg.m);
        t2 = a.t * Math.pow(tg.m / a.d, RIEGEL_R);
      }} else {{
        t2 = Infinity;
        for (const a of anchors) {{
          const v = a.t * Math.pow(tg.m / a.d, RIEGEL_R);
          if (v < t2) t2 = v;
        }}
      }}
      return {{ label:tg.l, value:clockHMS(t2), sub:projSub(tg.m / t2) }};
    }}
    let d2;
    if (mode === "nearest") {{
      const a = nearestBy("t", tg.s);
      d2 = a.d * Math.pow(tg.s / a.t, 1 / RIEGEL_R);
    }} else {{
      d2 = 0;
      for (const a of anchors) {{
        const v = a.d * Math.pow(tg.s / a.t, 1 / RIEGEL_R);
        if (v > d2) d2 = v;
      }}
    }}
    return {{ label:tg.l, value:Math.round(d2).toLocaleString() + " m", sub:projSub(d2 / tg.s) }};
  }});
}}

// Re-render only the projection cards (used by renderPowerCurve and the anchor
// toggle, so switching modes does not rebuild the chart).
function renderPcProjCards() {{
  const host = document.getElementById("pc-proj-cards");
  const hint = document.getElementById("pc-anchor-hint");
  if (!pcLastCurve || !pcLastCurve.length) {{ host.innerHTML = ""; if (hint) hint.textContent = ""; return; }}
  if (hint) hint.textContent = pcAnchorMode === "nearest"
    ? "· each target from the single closest-duration effort"
    : "· each target takes the strongest projection across all eligible efforts";
  const cards = projectFromCurve(pcLastCurve, pcAnchorMode) || [];
  host.innerHTML = cards.map(c =>
    `<div class="card"><div class="card-label">${{c.label}}</div><div class="card-value">${{c.value}}</div><div class="card-sub">${{c.sub}}</div></div>`).join("");
}}

function renderPowerCurve(data) {{
  const series = data
    .map(r => ({{ id:r.id, date:r.date, s:workoutWorkSeries(r.id) }}))
    .filter(x => x.s);
  const curve = powerCurveFromSeries(series);
  const note = document.getElementById("pc-note");

  if (!curve.length) {{
    if (pcChartInstance) {{ pcChartInstance.destroy(); pcChartInstance = null; }}
    note.textContent = "Not enough per-stroke or per-split data in this range to build a power curve.";
    pcLastCurve = null;
    renderPcProjCards();
    return;
  }}

  const anchored = curve.filter(c => c.D >= 300).length;
  note.innerHTML = `Best sustained average power at each duration across the ` +
    `${{series.length}} workout${{series.length === 1 ? "" : "s"}} with time-series data in range. ` +
    `Projections use only efforts ≥ 5 min as Riegel anchors ` +
    `(${{anchored}} point${{anchored === 1 ? "" : "s"}}); shorter sprints are excluded.`;

  // Power curve chart: watts vs duration (log time axis).
  const points = curve.map(c => ({{ x: c.D, y: Math.round(c.p) }}));
  if (pcChartInstance) pcChartInstance.destroy();
  pcChartInstance = new Chart(document.getElementById("pc-chart"), {{
    type: "line",
    data: {{ datasets: [{{
      label: "Max average power",
      data: points,
      borderColor: "#e94560",
      backgroundColor: "#e9456014",
      borderWidth: 2.5,
      pointRadius: 1.5,
      pointHoverRadius: 5,
      pointBackgroundColor: "#e94560",
      tension: 0.25,
      fill: true,
    }}] }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      interaction: {{ mode: "nearest", intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{
          title(items) {{ return clockHMS(items[0].parsed.x); }},
          label(ctx) {{ return ` ${{ctx.parsed.y}} W`; }},
        }} }}
      }},
      scales: {{
        x: {{
          type: "logarithmic", min: curve[0].D,
          title: {{ display:true, text:"Duration", font:{{ size:11 }} }},
          ticks: {{ font:{{ size:11 }}, callback:v => clockHMS(v) }},
          grid: {{ color:"rgba(0,0,0,.05)" }}
        }},
        y: {{
          title: {{ display:true, text:"Watts", color:"#e94560", font:{{ size:11 }} }},
          ticks: {{ font:{{ size:11 }}, color:"#e94560" }},
          grid: {{ color:"rgba(0,0,0,.05)" }}
        }}
      }}
    }}
  }});

  pcLastCurve = curve;
  renderPcProjCards();
}}

function renderDetail(id) {{
  const d = DETAIL[id];
  if (!d) return;
  document.getElementById("d-title").textContent = fmtDate(d.date);
  const target = d.targets || {{}};
  const targetBits = [];
  if (target.watts)       targetBits.push(`target ${{target.watts}} W`);
  if (target.stroke_rate) targetBits.push(`target ${{target.stroke_rate}} spm`);
  document.getElementById("d-meta").innerHTML =
    `<span class="badge">${{d.workout_type || d.type}}</span>` +
    `<span style="margin-left:10px">${{d.source || ""}}</span>` +
    (targetBits.length ? `<span style="margin-left:10px">· ${{targetBits.join(" · ")}}</span>` : "");
  renderDetailCards(d);
  renderChartControls(d);
  renderDetailChart(d);
  renderEffortCards(d);
  renderSplitsTable(d);
  renderProjCards(d);
}}

// ── Hash routing (list ⇄ detail) ──────────────────────────────────────────────
function currentDetailId() {{
  const prefix = "#/w/";
  const h = location.hash;
  return h.indexOf(prefix) === 0 ? (h.slice(prefix.length) || null) : null;
}}

function route() {{
  const id = currentDetailId();
  if (id && DETAIL[id]) {{
    renderDetail(id);
    document.body.classList.add("detail");
    window.scrollTo(0, 0);
  }} else {{
    document.body.classList.remove("detail");
  }}
}}

// ── Coordinated filter pipeline ───────────────────────────────────────────────
function applyFilters() {{
  const scoped = dateFiltered();
  scopedData = scoped;
  renderCards(scoped);
  renderMainControls(scoped);
  renderChart(scoped);
  renderEffortTrends(scoped);
  renderPowerCurve(scoped);

  tableData = scoped.filter(r => {{
    if (!searchQuery) return true;
    return r.date.includes(searchQuery) ||
      String(r.distance).includes(searchQuery) ||
      (r.pace_fmt||"").includes(searchQuery) ||
      (r.workout_type||"").toLowerCase().includes(searchQuery);
  }});
  page = 1;
  applySort();
  updateFilterSummary(scoped.length);
}}

function updateFilterSummary(n) {{
  const el = document.getElementById("filter-summary");
  if (!dateFrom && !dateTo) {{ el.textContent = ""; return; }}
  el.textContent = `${{n}} of ${{DATA.length}} workouts · ${{dateFrom || "start"}} → ${{dateTo || "latest"}}`;
}}

// ── Wiring ────────────────────────────────────────────────────────────────────
(function init() {{
  const dates = DATA.map(r => r.date.slice(0,10)).sort();
  const min = dates[0], max = dates[dates.length-1];
  const fromEl = document.getElementById("date-from");
  const toEl   = document.getElementById("date-to");
  if (min) {{ fromEl.min = min; toEl.min = min; }}
  if (max) {{ fromEl.max = max; toEl.max = max; }}

  // Default range: start on 27 Apr, open end (clamped to available data).
  fromEl.value = dateFrom && (!min || dateFrom >= min) ? dateFrom : (min || "");
  dateFrom = fromEl.value || null;

  fromEl.addEventListener("change", e => {{ dateFrom = e.target.value || null; applyFilters(); }});
  toEl.addEventListener("change",   e => {{ dateTo   = e.target.value || null; applyFilters(); }});

  document.getElementById("filter-reset").addEventListener("click", () => {{
    dateTo = null; searchQuery = "";
    fromEl.value = DEFAULT_DATE_FROM && (!min || DEFAULT_DATE_FROM >= min) ? DEFAULT_DATE_FROM : (min || "");
    dateFrom = fromEl.value || null;
    toEl.value = "";
    document.getElementById("search").value = "";
    applyFilters();
  }});

  document.getElementById("search").addEventListener("input", e => {{
    searchQuery = e.target.value.toLowerCase();
    applyFilters();
  }});

  document.getElementById("pc-anchor-mode").addEventListener("change", e => {{
    pcAnchorMode = e.target.value;
    renderPcProjCards();
  }});

  document.querySelectorAll("thead th[data-col]").forEach(th =>
    th.addEventListener("click", () => sortBy(th.dataset.col)));

  document.getElementById("prev-btn").addEventListener("click", () => {{ page--; renderRows(); }});
  document.getElementById("next-btn").addEventListener("click", () => {{ page++; renderRows(); }});

  // Row click → open workout detail (delegated; rows are re-rendered on sort/filter).
  document.getElementById("tbody").addEventListener("click", e => {{
    const tr = e.target.closest("tr.clickable");
    if (tr) location.hash = "#/w/" + tr.dataset.id;
  }});

  document.getElementById("back-btn").addEventListener("click", () => {{ location.hash = ""; }});

  // Main chart axis selectors — redraw against the current date-filtered set.
  document.getElementById("main-primary").addEventListener("change", e => {{
    activeMainPrimary = e.target.value; renderMainControls(scopedData); renderChart(scopedData);
  }});
  document.getElementById("main-secondary").addEventListener("change", e => {{
    activeMainSecondary = e.target.value; renderMainControls(scopedData); renderChart(scopedData);
  }});
  document.getElementById("main-powermodel").addEventListener("change", e => {{
    powerModel = e.target.value;
    renderChart(scopedData);
    // Keep the detail "Avg Power" card in sync if a workout is open.
    const id = currentDetailId();
    if (id && DETAIL[id]) renderDetailCards(DETAIL[id]);
  }});

  // Chart axis / overlay controls — redraw on change.
  function refreshChart() {{
    const id = currentDetailId();
    if (id && DETAIL[id]) {{ renderChartControls(DETAIL[id]); renderDetailChart(DETAIL[id]); }}
  }}
  document.getElementById("d-primary").addEventListener("change", e => {{
    activePrimary = e.target.value; refreshChart();
  }});
  document.getElementById("d-secondary").addEventListener("change", e => {{
    activeSecondary = e.target.value; refreshChart();
  }});
  document.getElementById("d-show-splits").addEventListener("change", e => {{
    showSplits = e.target.checked; refreshChart();
  }});

  window.addEventListener("hashchange", route);

  const refreshBtn = document.getElementById("refresh-btn");
  const servedFromFile = location.protocol === "file:";
  refreshBtn.addEventListener("click", async () => {{
    // Refresh needs the backend (it re-runs the OAuth fetch + rebuild). Opened
    // straight from disk there is no server to call, so guide the user instead
    // of firing a fetch that fails with a cryptic "Failed to fetch".
    if (servedFromFile) {{
      alert("This page was opened directly from a file, so it can't refresh.\\n\\n" +
        "Start the local server and open the dashboard from there:\\n" +
        "    python3 serve.py\\n\\n" +
        "then visit  http://localhost:8000/");
      return;
    }}
    const original = refreshBtn.textContent;
    refreshBtn.disabled = true;
    refreshBtn.textContent = "↻ Refreshing… (~1 min)";
    try {{
      const resp = await fetch("/api/refresh", {{ method: "POST" }});
      if (!resp.ok) throw new Error(await resp.text() || ("HTTP " + resp.status));
      location.reload();   // server has rebuilt dashboard.html with fresh data
    }} catch (err) {{
      refreshBtn.disabled = false;
      refreshBtn.textContent = original;
      alert("Refresh failed:\\n" + err.message +
        "\\n\\nIs the server still running?  Start it with:\\n    python3 serve.py");
    }}
  }});

  applyFilters();
  route();   // honor a #/w/<id> deep link on first load
}})();
</script>
</body>
</html>
"""

Path("dashboard.html").write_text(html)
print("dashboard.html written.")
