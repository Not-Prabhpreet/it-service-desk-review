"""Create the desk's SharePoint lists and load the rules tables (idempotent).

Lists:
  IT Tickets                 the ticket store the flows write to and Power BI reads
  Desk Rules - Keywords      keyword -> category        (rules/keywords.csv)
  Desk Rules - Impact        keyword -> impact          (rules/impact_keywords.csv)
  Desk Rules - Priority      impact x urgency -> priority + resolve hours (rules/priority_matrix.csv)
List IDs are written back to desk_config.json.
"""
import csv
from pathlib import Path
from urllib.parse import urlparse

import requests

from ms_auth import config, save_config, token

RULES = Path(__file__).resolve().parents[1] / "rules"
G = "https://graph.microsoft.com/v1.0"

choice = lambda *c: {"choice": {"choices": list(c), "displayAs": "dropDownMenu"}}
text = {"text": {}}
note = {"text": {"allowMultipleLines": True}}
when = {"dateTime": {"format": "dateTime"}}
number = {"number": {}}
yesno = {"boolean": {}}

LISTS = {
    "IT Tickets": [
        ("RequesterName", text), ("RequesterEmail", text), ("Service", text), ("Description", note),
        ("Urgency", choice("High", "Medium", "Low")), ("Impact", choice("High", "Medium", "Low")),
        ("Category", text), ("Priority", choice("P1 Critical", "P2 High", "P3 Moderate", "P4 Low")),
        ("AssignedTo", text),
        ("Status", choice("New", "In Progress", "Waiting on User", "Resolved", "Closed")),
        ("OpenedAt", when), ("SlaDueAt", when), ("WarnAt", when), ("WarnSent", yesno), ("Escalated", yesno),
        ("ResolvedAt", when), ("ResolutionHours", number), ("MetSLA", choice("Yes", "No")),
        ("ResolutionNotes", note), ("ResponseId", text),
    ],
    "Desk Rules - Keywords": [("Category", text)],
    "Desk Rules - Impact": [("Impact", text)],
    "Desk Rules - Priority": [("Impact", text), ("Urgency", text), ("Priority", text), ("ResolveHours", number)],
}
SEED = {
    "Desk Rules - Keywords": ("keywords.csv", lambda r: {"Title": r["Keyword"], "Category": r["Category"]}),
    "Desk Rules - Impact": ("impact_keywords.csv", lambda r: {"Title": r["Keyword"], "Impact": r["Impact"]}),
    "Desk Rules - Priority": ("priority_matrix.csv", lambda r: {
        "Title": f"{r['Impact']} x {r['Urgency']}", "Impact": r["Impact"], "Urgency": r["Urgency"],
        "Priority": r["Priority"], "ResolveHours": float(r["ResolveHours"])}),
}


def main():
    cfg = config()
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token('graph')}"
    host = urlparse(cfg["site_url"]).netloc
    site = s.get(f"{G}/sites/{host}:/").json()
    site_id = site["id"]
    existing = {l["displayName"]: l["id"] for l in s.get(f"{G}/sites/{site_id}/lists?$top=200").json()["value"]}
    ids = {}
    for name, cols in LISTS.items():
        if name in existing:
            ids[name] = existing[name]
            print(f"exists : {name}")
        else:
            body = {"displayName": name, "list": {"template": "genericList"},
                    "columns": [{"name": c, **spec} for c, spec in cols]}
            r = s.post(f"{G}/sites/{site_id}/lists", json=body)
            r.raise_for_status()
            ids[name] = r.json()["id"]
            print(f"created: {name}")
        if name in SEED:
            items = s.get(f"{G}/sites/{site_id}/lists/{ids[name]}/items?$top=1").json()["value"]
            if not items:
                fname, mapper = SEED[name]
                with open(RULES / fname, newline="") as fh:
                    rows = list(csv.DictReader(fh))
                for row in rows:
                    s.post(f"{G}/sites/{site_id}/lists/{ids[name]}/items", json={"fields": mapper(row)}).raise_for_status()
                print(f"  loaded {len(rows)} rules")
    cfg["site_id"] = site_id
    cfg["lists"] = ids
    save_config(cfg)
    print("lists:", ids)


if __name__ == "__main__":
    main()
