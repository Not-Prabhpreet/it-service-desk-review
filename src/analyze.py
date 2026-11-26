"""Step 2: compute every number the docs quote, pick the recurring problem, draw doc charts.

Writes data/clean/metrics.json (the single source for all numbers in README/RCA/runbook)
and docs/figures/*.png.
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import BLUE, CLEAN_DIR, FIG_DIR, GREY, GRID, INK, INK2, METRICS_JSON, ORANGE

MONTHS_LABEL = {"2016-03": "Mar 2016", "2016-04": "Apr 2016", "2016-05": "May 2016"}


def load():
    f = pd.read_csv(CLEAN_DIR / "fact_incident.csv", parse_dates=["opened_at", "resolved_at"])
    f["breach"] = f["met_sla_flag"] == 0
    f["is_reassigned"] = f["reassignment_count"] > 0
    f["is_reopened"] = f["reopen_count"] > 0
    return f


def r(x, n=1):
    if pd.isna(x):
        return None
    return int(round(float(x), n)) if n <= 0 else round(float(x), n)


def backlog_daily(f):
    days = pd.date_range(f.opened_at.min().normalize(), "2016-05-31", freq="D")
    end = days + pd.Timedelta(days=1)
    o = np.sort(f.opened_at.values)
    res = f.resolved_at.fillna(pd.Timestamp("2100-01-01")).values
    res = np.sort(res)
    opened_le = np.searchsorted(o, end.values, side="left")
    resolved_le = np.searchsorted(res, end.values, side="left")
    return pd.Series(opened_le - resolved_le, index=days)


def style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG_DIR / name, dpi=150, facecolor="white")
    plt.close(fig)


def main():
    f = load()
    m = {}
    N = len(f)
    B = int(f.breach.sum())
    months = sorted(f.month.unique())
    m["overall"] = dict(
        tickets=N, months=len(months), tickets_per_month=r(N / len(months), 0),
        breaches=B, sla_pct=r(100 * (1 - B / N)),
        median_res_h=r(f.resolution_hours.median()), mean_res_h=r(f.resolution_hours.mean()),
        p90_res_h=r(f.resolution_hours.quantile(.9)),
        reassign_rate=r(100 * f.is_reassigned.mean()), avg_reassign=r(f.reassignment_count.mean(), 2),
        reopen_rate=r(100 * f.is_reopened.mean()),
        repeat_rate=r(100 * (f.repeat_7d == "Yes").mean()),
        moderate_share=r(100 * (f.priority == "3 - Moderate").mean()),
        window_label=f"{MONTHS_LABEL[months[0]]} - {MONTHS_LABEL[months[-1]]}",
    )

    # Monthly
    mo = f.groupby("month").agg(tickets=("incident_id", "size"), breaches=("breach", "sum"),
                                median_h=("resolution_hours", "median"),
                                reassign=("is_reassigned", "mean"), reopen=("is_reopened", "mean"))
    mo["sla_pct"] = 100 * (1 - mo.breaches / mo.tickets)
    bl = backlog_daily(f)
    mo["backlog_month_end"] = [int(bl[bl.index.strftime("%Y-%m") == k].iloc[-1]) for k in mo.index]
    m["monthly"] = {k: dict(label=MONTHS_LABEL[k], tickets=int(v.tickets), sla_pct=r(v.sla_pct),
                            median_h=r(v.median_h), reassign_rate=r(100 * v.reassign),
                            reopen_rate=r(100 * v.reopen), backlog=int(v.backlog_month_end))
                    for k, v in mo.iterrows()}
    a, b = mo.iloc[-2], mo.iloc[-1]
    m["mom"] = dict(tickets_pct=r(100 * (b.tickets / a.tickets - 1)),
                    sla_pts=r(b.sla_pct - a.sla_pct), from_label=MONTHS_LABEL[mo.index[-2]],
                    to_label=MONTHS_LABEL[mo.index[-1]])
    m["backlog"] = dict(peak=int(bl.max()), peak_date=bl.idxmax().strftime("%d %b %Y"),
                        end=int(bl.iloc[-1]))

    # Priority
    pr = f.groupby("priority").agg(n=("incident_id", "size"), breach=("breach", "sum"),
                                   med=("resolution_hours", "median"))
    m["priority"] = {k: dict(tickets=int(v.n), share=r(100 * v.n / N), sla_pct=r(100 * (1 - v.breach / v.n)),
                             median_h=r(v.med)) for k, v in pr.iterrows()}
    p12 = f.priority.isin(["1 - Critical", "2 - High"])
    m["p1p2"] = dict(tickets=int(p12.sum()), sla_pct=r(100 * (1 - f[p12].breach.mean())),
                     median_h=r(f[p12].resolution_hours.median()))

    # Categories
    cat = f.groupby("category").agg(n=("incident_id", "size"), breach=("breach", "sum"),
                                    reass=("is_reassigned", "mean"), reop=("is_reopened", "mean"),
                                    med=("resolution_hours", "median"),
                                    hours=("resolution_hours", "sum")).sort_values("n", ascending=False)
    cat["share"] = 100 * cat.n / N
    cat["breach_share"] = 100 * cat.breach / B
    cat["breach_rate"] = 100 * cat.breach / cat.n
    cat["cum_share"] = cat.share.cumsum()
    m["categories"] = dict(
        count=int(len(cat)),
        top5_share=r(cat.share.head(5).sum()), top10_share=r(cat.share.head(10).sum()),
        n_for_80pct=int((cat.cum_share < 80).sum() + 1),
        top_by_volume=[dict(category=k, tickets=int(v.n), share=r(v.share), breach_rate=r(v.breach_rate))
                       for k, v in cat.head(10).iterrows()],
        top_by_breaches=[dict(category=k, breaches=int(v.breach), breach_share=r(v.breach_share),
                              breach_rate=r(v.breach_rate))
                         for k, v in cat.sort_values("breach", ascending=False).head(10).iterrows()],
    )

    # Groups
    grp = f.groupby("assignment_group").agg(n=("incident_id", "size"), breach=("breach", "sum"),
                                            med=("resolution_hours", "median"),
                                            reass=("is_reassigned", "mean"))
    grp = grp[grp.index != "Not recorded"].sort_values("n", ascending=False)
    first_line = grp.index[0]   # largest group; also the fastest - see data_notes.md
    m["first_line"] = dict(group=first_line, tickets=int(grp.loc[first_line, "n"]),
                           share=r(100 * grp.loc[first_line, "n"] / N),
                           median_h=r(grp.loc[first_line, "med"]))
    big = grp[grp.n >= 100].copy()
    big["breach_rate"] = 100 * big.breach / big.n
    m["worst_groups"] = [dict(group=k, tickets=int(v.n), breach_rate=r(v.breach_rate), median_h=r(v.med))
                         for k, v in big.sort_values("breach_rate", ascending=False).head(5).iterrows()]

    # Reassignment effect (all tickets)
    ra = f.groupby("is_reassigned").agg(med=("resolution_hours", "median"), br=("breach", "mean"))
    m["reassign_effect"] = dict(med_h_no=r(ra.loc[False, "med"]), med_h_yes=r(ra.loc[True, "med"]),
                                breach_no=r(100 * ra.loc[False, "br"]), breach_yes=r(100 * ra.loc[True, "br"]))

    # ---- Recurring problem: the category contributing the most SLA breaches ----
    pc = cat.breach.idxmax()
    c = f[f.category == pc]
    rest = f[f.category != pc]
    cn, cb = len(c), int(c.breach.sum())
    per_month = len(months)
    cra = c.groupby("is_reassigned").agg(n=("incident_id", "size"), med=("resolution_hours", "median"),
                                         br=("breach", "mean"))
    reassigned_pm = cra.loc[True, "n"] / per_month
    delta_h = cra.loc[True, "med"] - cra.loc[False, "med"]
    delta_br = cra.loc[True, "br"] - cra.loc[False, "br"]
    halved = reassigned_pm / 2
    hours_saved = halved * delta_h
    breaches_avoided = halved * delta_br
    new_cat_breach_rate = 100 * (cb / per_month - breaches_avoided) / (cn / per_month)
    new_overall_sla = 100 * (1 - (B / per_month - breaches_avoided) / (N / per_month))
    fl_c = (c.assignment_group == first_line).mean()
    fl_rest = (rest.assignment_group == first_line).mean()
    cg = c[c.assignment_group != "Not recorded"].groupby("assignment_group").agg(
        n=("incident_id", "size"), med=("resolution_hours", "median"), br=("breach", "mean")
    ).sort_values("n", ascending=False)
    sub = c.subcategory.value_counts()
    cm = c.groupby("month").agg(n=("incident_id", "size"), br=("breach", "mean"),
                                reass=("is_reassigned", "mean"),
                                fl=("assignment_group", lambda s: (s == first_line).mean()))
    # Scenario A (primary): bring first-line resolution of this category up to the rest-of-desk rate.
    at_fl = c[c.assignment_group == first_line]
    not_fl = c[(c.assignment_group != first_line) & (c.assignment_group != "Not recorded")]
    shift_pm = (fl_rest - fl_c) * cn / per_month
    fl_delta_h = not_fl.resolution_hours.median() - at_fl.resolution_hours.median()
    fl_delta_br = not_fl.breach.mean() - at_fl.breach.mean()
    fl_breaches_avoided = shift_pm * fl_delta_br
    # "Hours lost": customer wait above the rest-of-desk median, per month (elapsed, not effort).
    excess = (c.resolution_hours - rest.resolution_hours.median()).clip(lower=0).sum() / per_month
    m["problem_scenario_fl"] = dict(
        target_share=r(100 * fl_rest), tickets_shifted_pm=r(shift_pm, 0),
        med_h_first_line=r(at_fl.resolution_hours.median(), 2), med_h_other=r(not_fl.resolution_hours.median()),
        breach_first_line=r(100 * at_fl.breach.mean()), breach_other=r(100 * not_fl.breach.mean()),
        hours_saved_pm=r(shift_pm * fl_delta_h, -2), breaches_avoided_pm=r(fl_breaches_avoided, 0),
        new_cat_breach_rate=r(100 * (cb / per_month - fl_breaches_avoided) / (cn / per_month))
        , new_overall_sla=r(100 * (1 - (B / per_month - fl_breaches_avoided) / (N / per_month))),
    )
    lm = months[-1]
    lm_br = 100 * cm.loc[lm, "br"]
    lm_desk_sla = 100 * (1 - f[f.month == lm].breach.mean())
    sc = m["problem_scenario_fl"]
    m["latest"] = dict(
        label=MONTHS_LABEL[lm], desk_sla_pct=r(lm_desk_sla), desk_breach_rate=r(100 - lm_desk_sla),
        problem_breach_rate=r(lm_br), problem_first_line_share=r(100 * cm.loc[lm, "fl"]),
        # targets keep the scenario's relative improvement, applied to the latest month
        target_problem_breach_rate=r(lm_br * sc["new_cat_breach_rate"] / (100 * cb / cn)),
        target_desk_sla_pct=r(lm_desk_sla + sc["new_overall_sla"] - 100 * (1 - B / N)),
    )
    m["problem"] = dict(
        excess_wait_hours_pm=r(excess, -2),
        category=pc, tickets=cn, tickets_pm=r(cn / per_month, 0), share=r(100 * cn / N),
        volume_rank=int(list(cat.index).index(pc) + 1),
        breaches=cb, breaches_pm=r(cb / per_month, 0), breach_share=r(100 * cb / B),
        breach_rate=r(100 * cb / cn), breach_rate_rest=r(100 * rest.breach.mean()),
        median_h=r(c.resolution_hours.median()), median_h_rest=r(rest.resolution_hours.median()),
        hours_total=r(c.resolution_hours.sum(), 0), hours_share=r(100 * c.resolution_hours.sum() / f.resolution_hours.sum()),
        breached_hours_pm=r(c[c.breach].resolution_hours.sum() / per_month, 0),
        reassign_rate=r(100 * c.is_reassigned.mean()), reassign_rate_rest=r(100 * rest.is_reassigned.mean()),
        repeat_rate=r(100 * (c.repeat_7d == "Yes").mean()), repeat_rate_rest=r(100 * (rest.repeat_7d == "Yes").mean()),
        reopen_rate=r(100 * c.is_reopened.mean(), 2), reopen_rate_rest=r(100 * rest.is_reopened.mean(), 2),
        groups_touched_avg=r(c.groups_touched.mean(), 2), groups_touched_rest=r(rest.groups_touched.mean(), 2),
        resolver_groups=int(c.assignment_group.nunique()),
        top5_group_share=r(100 * cg.n.head(5).sum() / cn),
        first_line_share=r(100 * fl_c), first_line_share_rest=r(100 * fl_rest),
        first_line_med_h=r(c[c.assignment_group == first_line].resolution_hours.median(), 2),
        other_groups_med_h=r(c[c.assignment_group != first_line].resolution_hours.median()),
        knowledge_rate=r(100 * (c.knowledge_used == "Yes").mean()),
        knowledge_rate_rest=r(100 * (rest.knowledge_used == "Yes").mean()),
        problem_link_rate=r(100 * (c.linked_problem == "Yes").mean()),
        problem_link_rate_rest=r(100 * (rest.linked_problem == "Yes").mean()),
        awaiting_user_rate=r(100 * (c.awaiting_user_events > 0).mean()),
        awaiting_user_rate_rest=r(100 * (rest.awaiting_user_events > 0).mean()),
        moderate_share=r(100 * (c.priority == "3 - Moderate").mean()),
        top_subcategory=sub.index[0], top_subcategory_share=r(100 * sub.iloc[0] / cn),
        groups=[dict(group=k, tickets=int(v.n), median_h=r(v.med), breach_rate=r(100 * v.br))
                for k, v in cg.head(6).iterrows()],
        monthly={k: dict(label=MONTHS_LABEL[k], tickets=int(v.n), breach_rate=r(100 * v.br),
                         reassign_rate=r(100 * v.reass), first_line_share=r(100 * v.fl))
                 for k, v in cm.iterrows()},
        reassigned_pm=r(reassigned_pm, 0), med_h_reassigned=r(cra.loc[True, "med"]),
        med_h_not_reassigned=r(cra.loc[False, "med"]), delta_h=r(delta_h),
        breach_reassigned=r(100 * cra.loc[True, "br"]), breach_not_reassigned=r(100 * cra.loc[False, "br"]),
        proj_hours_saved_pm=r(hours_saved, -2), proj_breaches_avoided_pm=r(breaches_avoided, 0),
        proj_cat_breach_rate=r(new_cat_breach_rate), proj_overall_sla=r(new_overall_sla),
    )

    # Before/after table for the Power BI Problem Review page
    sc = m["problem_scenario_fl"]
    pd.DataFrame([
        ("First-line resolution %", 1, m["problem"]["first_line_share"], sc["target_share"]),
        ("Breach rate %", 2, m["problem"]["breach_rate"], sc["new_cat_breach_rate"]),
        ("Breaches per month", 3, m["problem"]["breaches_pm"], m["problem"]["breaches_pm"] - sc["breaches_avoided_pm"]),
        ("Desk SLA met %", 4, m["overall"]["sla_pct"], sc["new_overall_sla"]),
    ], columns=["metric", "metric_sort", "before", "after"]).to_csv(CLEAN_DIR / "problem_projection.csv", index=False)
    (CLEAN_DIR / "problem_config.csv").write_text(
        f"problem_category,first_line_group\n{pc},{first_line}\n")

    # ---- Figures ----
    labels = [MONTHS_LABEL[k] for k in mo.index]
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(labels, mo.tickets, color=BLUE, width=0.55)
    for i, v in enumerate(mo.tickets):
        ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=9, color=INK)
    style(ax, "Tickets opened per month")
    save(fig, "monthly_volume.png")

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(pr.index.str[4:], 100 * (1 - pr.breach / pr.n), color=BLUE, width=0.55)
    for i, v in enumerate(100 * (1 - pr.breach / pr.n)):
        ax.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_ylim(0, 100)
    style(ax, "SLA met by priority (%)")
    save(fig, "sla_by_priority.png")

    top = cat.head(15)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    colors = [ORANGE if k == pc else BLUE for k in top.index]
    ax.bar(top.index.str.replace("Category ", "C"), top.share, color=colors, width=0.6)
    ax.plot(top.index.str.replace("Category ", "C"), top.cum_share, color=INK2, marker="o", markersize=4, linewidth=1.5)
    ax.axhline(80, color=GREY, linestyle="--", linewidth=1)
    ax.set_ylim(0, 100)
    style(ax, "Pareto: share of tickets by category (bars) and cumulative share (line), %")
    save(fig, "pareto_categories.png")

    tb = cat.sort_values("breach", ascending=False).head(10)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    x = np.arange(len(tb))
    ax.bar(x - 0.19, tb.share, 0.36, color=GREY, label="% of tickets")
    ax.bar(x + 0.19, tb.breach_share, 0.36, color=BLUE, label="% of SLA breaches")
    i0 = list(tb.index).index(pc)
    ax.annotate(f"{pc}: {tb.loc[pc, 'share']:.1f}% of tickets,\n{tb.loc[pc, 'breach_share']:.1f}% of breaches",
                xy=(i0 + 0.19, tb.loc[pc, "breach_share"]), xytext=(i0 + 1.2, tb.breach_share.max() * 1.02),
                fontsize=9, color=INK, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set_ylim(0, tb[["share", "breach_share"]].max().max() * 1.25)
    ax.set_xticks(x, tb.index.str.replace("Category ", "C"))
    ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    style(ax, "Top 10 categories by SLA breaches: share of tickets vs share of breaches")
    save(fig, "breach_share_vs_ticket_share.png")

    fig, ax = plt.subplots(figsize=(6, 3))
    vals = [cra.loc[False, "med"], cra.loc[True, "med"]]
    ax.bar(["Not reassigned", "Reassigned 1+ times"], vals, color=[BLUE, ORANGE], width=0.5)
    for i, v in enumerate(vals):
        ax.text(i, v, f"{v:.0f} h", ha="center", va="bottom", fontsize=9, color=INK)
    style(ax, f"{pc}: median hours to resolve")
    save(fig, "problem_reassignment_effect.png")

    g6 = cg.head(6)
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.barh(g6.index[::-1], g6.med[::-1], color=[BLUE if k == first_line else GREY for k in g6.index[::-1]])
    for i, v in enumerate(g6.med[::-1]):
        ax.text(v, i, f" {v:.1f} h" if v < 10 else f" {v:.0f} h", va="center", fontsize=9, color=INK)
    style(ax, f"{pc}: median hours to resolve, by resolving group")
    ax.grid(axis="x", color=GRID); ax.grid(axis="y", visible=False)
    save(fig, "problem_groups.png")

    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(bl.index, bl.values, color=BLUE, linewidth=2)
    style(ax, "Open backlog at end of each day")
    save(fig, "backlog_trend.png")

    METRICS_JSON.write_text(json.dumps(m, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"analyze: problem = {pc} ({m['problem']['share']}% of tickets, "
          f"{m['problem']['breach_share']}% of breaches); metrics -> {METRICS_JSON.name}")


if __name__ == "__main__":
    main()
