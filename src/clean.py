"""Step 1: collapse the ServiceNow event log to one row per incident and build the star schema.

Outputs (data/clean/):
  fact_incident.csv          one row per incident in the reporting window
  dim_date.csv               calendar for the reporting window
  dim_category.csv, dim_priority.csv, dim_assignment_group.csv
  cleaning_log.json          every count quoted in docs/data_notes.md
"""
import io
import json
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from config import CLEAN_DIR, RAW_CSV, RAW_DIR, RAW_URL, WINDOW_END, WINDOW_START

DATE_COLS = ["opened_at", "sys_updated_at", "sys_created_at", "resolved_at", "closed_at"]
DATE_FMT = "%d/%m/%Y %H:%M"
PRIORITY_ORDER = {"1 - Critical": 1, "2 - High": 2, "3 - Moderate": 3, "4 - Low": 4}


def ensure_raw():
    if RAW_CSV.exists():
        return
    print(f"Downloading raw data from {RAW_URL}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(RAW_URL) as r:
        zipfile.ZipFile(io.BytesIO(r.read())).extract("incident_event_log.csv", RAW_DIR)


def main():
    ensure_raw()
    log = {}
    # '?' is the dataset's missing-value marker.
    ev = pd.read_csv(RAW_CSV, low_memory=False, na_values="?")
    log["raw_events"] = len(ev)
    log["raw_columns"] = ev.shape[1]
    log["raw_incidents"] = int(ev["number"].nunique())
    for c in DATE_COLS:
        ev[c] = pd.to_datetime(ev[c], format=DATE_FMT)

    log["events_state_minus100"] = int((ev["incident_state"] == "-100").sum())
    log["events_dup_mod_count"] = int(ev.duplicated(["number", "sys_mod_count"]).sum())

    # Final state = last event by sys_mod_count, ties broken by sys_updated_at.
    ev = ev.sort_values(["number", "sys_mod_count", "sys_updated_at"], kind="mergesort")
    last = ev.groupby("number", sort=False).tail(1).set_index("number")
    log["final_state_counts"] = last["incident_state"].value_counts().to_dict()

    # Per-incident event features that the final row alone does not carry.
    g = ev.groupby("number")
    first_group = ev.dropna(subset=["assignment_group"]).groupby("number")["assignment_group"].first()
    resolved_evt = ev[ev["incident_state"] == "Resolved"].groupby("number")["sys_updated_at"].max()
    n_groups = g["assignment_group"].nunique()
    n_events = g.size()
    awaiting_user = ev[ev["incident_state"] == "Awaiting User Info"].groupby("number").size()

    f = pd.DataFrame(index=last.index)
    f["opened_at"] = last["opened_at"]
    # resolved_at: field on final row; if blank, timestamp of the last 'Resolved' event.
    f["resolved_at"] = last["resolved_at"]
    missing = f["resolved_at"].isna()
    log["resolved_missing_final_row"] = int(missing.sum())
    f.loc[missing, "resolved_at"] = resolved_evt.reindex(f.index[missing])
    log["resolved_filled_from_event"] = int(missing.sum() - f["resolved_at"].isna().sum())
    log["resolved_still_missing"] = int(f["resolved_at"].isna().sum())
    f["resolved_source"] = np.where(~missing, "resolved_at field",
                                    np.where(f["resolved_at"].notna(), "last Resolved event", "unknown"))
    f["closed_at"] = last["closed_at"]

    f["priority"] = last["priority"]
    f["impact"] = last["impact"]
    f["urgency"] = last["urgency"]
    f["category"] = last["category"].fillna("Unknown")
    f["subcategory"] = last["subcategory"].fillna("Unknown")
    f["symptom"] = last["u_symptom"].fillna("Unknown")
    f["assignment_group"] = last["assignment_group"].fillna("Not recorded")
    f["first_assignment_group"] = first_group.reindex(f.index).fillna("Not recorded")
    f["groups_touched"] = n_groups.reindex(f.index).fillna(0).astype(int)
    f["caller_id"] = last["caller_id"].fillna("Unknown")
    f["contact_type"] = last["contact_type"]
    f["location"] = last["location"].fillna("Unknown")
    f["knowledge_used"] = np.where(last["knowledge"], "Yes", "No")
    f["linked_problem"] = np.where(last["problem_id"].notna(), "Yes", "No")
    f["closed_code"] = last["closed_code"].fillna("Unknown")
    f["event_count"] = n_events.reindex(f.index).astype(int)
    f["awaiting_user_events"] = awaiting_user.reindex(f.index).fillna(0).astype(int)
    log["missing_category"] = int(last["category"].isna().sum())
    log["missing_group"] = int(last["assignment_group"].isna().sum())

    # Required measures
    f["resolution_hours"] = ((f["resolved_at"] - f["opened_at"]).dt.total_seconds() / 3600).round(3)
    log["negative_resolution"] = int((f["resolution_hours"] < 0).sum())
    f["met_sla"] = np.where(last["made_sla"], "Yes", "No")
    f["met_sla_flag"] = last["made_sla"].astype(int)
    f["reassignment_count"] = last["reassignment_count"].astype(int)
    f["reassigned"] = np.where(f["reassignment_count"] > 0, "Yes", "No")
    f["reopen_count"] = last["reopen_count"].astype(int)
    f["reopened"] = np.where(f["reopen_count"] > 0, "Yes", "No")
    f["opened_date"] = f["opened_at"].dt.normalize()
    f["resolved_date"] = f["resolved_at"].dt.normalize()
    f["month"] = f["opened_at"].dt.strftime("%Y-%m")
    log["sla_flag_changed_within_incident"] = int((g["made_sla"].nunique() > 1).sum())
    log["reassign_final_equals_max"] = bool((g["reassignment_count"].max() == last["reassignment_count"]).all())
    log["reopen_final_equals_max"] = bool((g["reopen_count"].max() == last["reopen_count"]).all())

    # Reporting window
    log["opened_by_month_all"] = f["month"].value_counts().sort_index().to_dict()
    in_win = (f["opened_at"] >= WINDOW_START) & (f["opened_at"] < pd.Timestamp(WINDOW_END) + pd.Timedelta(days=1))
    log["excluded_outside_window"] = int((~in_win).sum())
    f = f[in_win].copy()
    log["fact_rows"] = len(f)
    log["window"] = [WINDOW_START, WINDOW_END]

    # Resolution-time outliers are kept (they are real long-running tickets); flag them.
    p99 = f["resolution_hours"].quantile(0.99)
    log["resolution_p99_hours"] = round(float(p99), 1)
    log["resolution_over_p99"] = int((f["resolution_hours"] > p99).sum())

    # Repeat ticket: same caller raised a ticket in the same category in the previous 7 days.
    f = f.sort_values(["caller_id", "category", "opened_at"])
    prev = f.groupby(["caller_id", "category"])["opened_at"].shift()
    rep = (f["opened_at"] - prev <= pd.Timedelta(days=7)) & (f["caller_id"] != "Unknown")
    f["repeat_7d"] = np.where(rep, "Yes", "No")
    log["repeat_7d"] = int(rep.sum())
    f = f.sort_index()

    # Resolution-time buckets for the distribution chart
    bins = [-0.001, 1, 4, 24, 72, 168, 672, np.inf]
    labels = ["< 1 h", "1-4 h", "4-24 h", "1-3 days", "3-7 days", "1-4 weeks", "> 4 weeks"]
    f["resolution_bucket"] = pd.cut(f["resolution_hours"], bins=bins, labels=labels).astype(str)
    f.loc[f["resolution_hours"].isna(), "resolution_bucket"] = "No resolve time"
    f["resolution_bucket_sort"] = f["resolution_bucket"].map(
        {l: i for i, l in enumerate(labels + ["No resolve time"], start=1)})

    f = f.reset_index().rename(columns={"number": "incident_id"})
    f["priority_sort"] = f["priority"].map(PRIORITY_ORDER)
    for c in ["opened_at", "resolved_at", "closed_at"]:
        f[c] = f[c].dt.strftime("%Y-%m-%d %H:%M")
    for c in ["opened_date", "resolved_date"]:
        f[c] = f[c].dt.strftime("%Y-%m-%d")
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    f.to_csv(CLEAN_DIR / "fact_incident.csv", index=False)

    # Dimensions
    # Calendar covers the reporting window only (resolve dates after it simply don't match a row).
    dates = pd.date_range(WINDOW_START, WINDOW_END, freq="D")
    dd = pd.DataFrame({"date": dates})
    dd["year"] = dd.date.dt.year
    dd["month"] = dd.date.dt.strftime("%Y-%m")
    dd["month_name"] = dd.date.dt.strftime("%b %Y")
    dd["month_start"] = dd.date.dt.to_period("M").dt.start_time
    dd["week_start"] = dd.date - pd.to_timedelta(dd.date.dt.day_of_week, unit="D")
    dd["weekday"] = dd.date.dt.strftime("%a")
    dd["month_sort"] = dd.date.dt.year * 100 + dd.date.dt.month
    for c in ["date", "month_start", "week_start"]:
        dd[c] = dd[c].dt.strftime("%Y-%m-%d")
    dd.to_csv(CLEAN_DIR / "dim_date.csv", index=False)

    cat = (f.groupby("category").size().rename("tickets").sort_values(ascending=False).reset_index())
    cat["volume_rank"] = np.arange(1, len(cat) + 1)
    cat[["category", "volume_rank"]].to_csv(CLEAN_DIR / "dim_category.csv", index=False)

    pr = pd.DataFrame({"priority": list(PRIORITY_ORDER), "priority_sort": list(PRIORITY_ORDER.values())})
    pr["priority_short"] = ["P1 Critical", "P2 High", "P3 Moderate", "P4 Low"]
    pr.to_csv(CLEAN_DIR / "dim_priority.csv", index=False)

    grp = f.groupby("assignment_group").size().rename("tickets").sort_values(ascending=False).reset_index()
    grp["volume_rank"] = np.arange(1, len(grp) + 1)
    grp[["assignment_group", "volume_rank"]].to_csv(CLEAN_DIR / "dim_assignment_group.csv", index=False)

    log = json.loads(json.dumps(log, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    (CLEAN_DIR / "cleaning_log.json").write_text(json.dumps(log, indent=2))
    print(f"clean: {log['raw_events']:,} events -> {log['fact_rows']:,} incidents in window "
          f"({log['excluded_outside_window']} outside window excluded)")


if __name__ == "__main__":
    main()
