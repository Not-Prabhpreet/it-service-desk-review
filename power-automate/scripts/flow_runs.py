"""Print recent runs of each desk flow (status, start time, failing action) and the newest tickets.

Usage: python flow_runs.py [n_runs]
"""
import sys

import requests

from ms_auth import config, token

V = "api-version=2016-11-01"


def main(n=5):
    c = config()
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token('flow')}"
    base = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{c['environment']}/flows"
    for name, fid in c["flows"].items():
        runs = s.get(f"{base}/{fid}/runs?{V}&$top={n}").json().get("value", [])
        print(f"\n{name}: {len(runs)} recent run(s)")
        for r in runs:
            p = r["properties"]
            line = f"  {p.get('startTime', '')[:19]}  {p.get('status')}"
            if p.get("status") == "Failed":
                acts = s.get(f"{base}/{fid}/runs/{r['name']}/actions?{V}").json().get("value", [])
                bad = [(a["name"], a["properties"].get("error", {}).get("message", "")[:300])
                       for a in acts if a["properties"].get("status") == "Failed"]
                line += f"  failed at: {bad}"
            print(line)
    g = requests.Session()
    g.headers["Authorization"] = f"Bearer {token('graph')}"
    items = g.get(f"https://graph.microsoft.com/v1.0/sites/{c['site_id']}/lists/{c['lists']['IT Tickets']}/items"
                  "?$expand=fields&$top=20").json().get("value", [])
    print("\nTickets:")
    for it in items:
        f = it["fields"]
        print(f"  {f.get('Title')} | {f.get('Priority')} | {f.get('Category')} | impact {f.get('Impact')} "
              f"urgency {f.get('Urgency')} | {f.get('Status')} | due {f.get('SlaDueAt')} | resolved {f.get('ResolvedAt')} "
              f"{f.get('ResolutionHours')} h met {f.get('MetSLA')}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
