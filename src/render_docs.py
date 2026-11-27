"""Step 4: fill the doc templates (docs/templates/*.md) with numbers from metrics.json + cleaning_log.json.

Placeholders are ${dotted_path_with_underscores}, e.g. ${problem_breach_share} or
${overall_sla_pct}. A missing placeholder raises an error, so no doc can ship with a
number that the code did not produce.
"""
import json
import re
from string import Template

from config import CLEAN_DIR, DOCS_DIR, METRICS_JSON, ROOT

TEMPLATES = {
    DOCS_DIR / "templates" / "data_notes.md": DOCS_DIR / "data_notes.md",
    DOCS_DIR / "templates" / "problem_review_rca.md": DOCS_DIR / "problem_review_rca.md",
    DOCS_DIR / "templates" / "runbook.md": None,  # name depends on the problem picked
    DOCS_DIR / "templates" / "README.md": ROOT / "README.md",
}


class Strict(Template):
    idpattern = r"[a-z0-9_]+"


def fmt(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if v.is_integer() and abs(v) >= 100:
            return f"{int(v):,}"
        return f"{v:,}"
    return str(v)


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = re.sub(r"[^a-z0-9]+", "_", f"{prefix}{k}".lower()).strip("_")
        if isinstance(v, dict):
            out.update(flatten(v, key + "_"))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if not isinstance(x, (dict, list)):
                    out[f"{key}_{i}"] = fmt(x)
        else:
            out[key] = fmt(v)
    return out


def table(rows, cols):
    head = "| " + " | ".join(c[0] for c in cols) + " |\n|" + "|".join(
        "---:" if c[2] else "---" for c in cols) + "|\n"
    return head + "".join("| " + " | ".join(fmt(r[c[1]]) for c in cols) + " |\n" for r in rows)


def tables(m):
    p = m["problem"]
    t = {}
    t["table_monthly"] = table(list(m["monthly"].values()), [
        ("Month", "label", 0), ("Tickets", "tickets", 1), ("SLA met %", "sla_pct", 1),
        ("Median hours", "median_h", 1), ("Reassigned %", "reassign_rate", 1),
        ("Reopened %", "reopen_rate", 1), ("Backlog at month end", "backlog", 1)])
    t["table_priority"] = table([dict(priority=k, **v) for k, v in m["priority"].items()], [
        ("Priority", "priority", 0), ("Tickets", "tickets", 1), ("% of tickets", "share", 1),
        ("SLA met %", "sla_pct", 1), ("Median hours", "median_h", 1)])
    t["table_top_breaches"] = table(m["categories"]["top_by_breaches"][:5], [
        ("Category", "category", 0), ("Breaches", "breaches", 1), ("% of all breaches", "breach_share", 1),
        ("Breach rate %", "breach_rate", 1)])
    t["table_problem_groups"] = table(p["groups"], [
        ("Resolving group", "group", 0), ("Tickets", "tickets", 1), ("Median hours", "median_h", 1),
        ("Breach rate %", "breach_rate", 1)])
    t["table_problem_monthly"] = table(list(p["monthly"].values()), [
        ("Month", "label", 0), ("Tickets", "tickets", 1), ("Breach rate %", "breach_rate", 1),
        ("Reassigned %", "reassign_rate", 1)])
    t["table_worst_groups"] = table(m["worst_groups"], [
        ("Group", "group", 0), ("Tickets", "tickets", 1), ("Breach rate %", "breach_rate", 1),
        ("Median hours", "median_h", 1)])
    g = p["groups"]
    fast = sorted([x for x in g if x["group"] != m["first_line"]["group"]], key=lambda x: x["median_h"])
    t["fastest_l2_group"], t["fastest_l2_median_h"] = fast[0]["group"], fmt(fast[0]["median_h"])
    t["slowest_l2_group"], t["slowest_l2_median_h"] = fast[-1]["group"], fmt(fast[-1]["median_h"])
    t["problem_slug"] = p["category"].lower().replace(" ", "_")
    t.update(live_sections())
    return t


def live_sections():
    """'Try it' and screenshot blocks, from power-automate/live_links.json and powerbi/screenshots/."""
    links_file = ROOT / "power-automate" / "live_links.json"
    links = json.loads(links_file.read_text()) if links_file.exists() else {}
    lines = []
    if links.get("form_url"):
        until = f" The live desk runs on a trial tenant until {links['live_until']}." if links.get("live_until") else ""
        lines.append(f"- **Submit a test IT request:** [open the form]({links['form_url']}). No account needed. "
                     "You'll get a confirmation email with your ticket number within a minute, and the ticket appears on the "
                     f"dashboard's Live Desk page after a refresh.{until} How it works and the test log: "
                     "[power-automate/README.md](power-automate/README.md).")
    else:
        lines.append("- **Live service desk:** being set up. See [power-automate/](power-automate/).")
    if links.get("dashboard_url"):
        lines.append(f"- **Live dashboard:** [{links['dashboard_url']}]({links['dashboard_url']})")
    pdf = ROOT / "powerbi" / "ServiceDesk.pdf"
    if pdf.exists():
        lines.append("- **Dashboard PDF:** [powerbi/ServiceDesk.pdf](powerbi/ServiceDesk.pdf). Screenshots are below.")
    shots = sorted((ROOT / "powerbi" / "screenshots").glob("*.png"))
    if shots:
        shot_md = "\n\n".join(f"![{s.stem.replace('_', ' ')}](powerbi/screenshots/{s.name})" for s in shots)
    else:
        shot_md = ("Dashboard screenshots will appear here once exported. Meanwhile, the charts in "
                   "[docs/figures/](docs/figures/) come from the same numbers.")
    return {"try_it": "\n".join(lines), "screenshots": shot_md}


def main():
    m = json.loads(METRICS_JSON.read_text())
    log = json.loads((CLEAN_DIR / "cleaning_log.json").read_text())
    values = flatten(m)
    values.update({f"log_{k}": v for k, v in flatten(log).items()})
    values.update(tables(m))
    for src, dst in TEMPLATES.items():
        if not src.exists():
            continue
        if dst is None:
            dst = DOCS_DIR / f"runbook_{values['problem_slug']}.md"
        text = Strict(src.read_text(encoding="utf-8")).substitute(values)
        dst.write_text(text, encoding="utf-8")
        print(f"docs: wrote {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
