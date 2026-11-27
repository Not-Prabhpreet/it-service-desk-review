"""End-to-end test of the non-intake flows, run after the sample form submissions.

1. Resolution:  marks INC-00003 Resolved with notes, as an agent would in the SharePoint list.
2. SLA watch:   SIMULATED TIME. Moves INC-00002's warning time and INC-00001's due time into the
                past so the 75% warning and the breach escalation fire now instead of hours later.
                Both changes are written to each ticket's ResolutionNotes so they're visible in the list.
3. Runs SLA watch and Daily digest immediately (their schedules would otherwise run them later).
"""
from datetime import datetime, timedelta, timezone

import requests

from ms_auth import config, token

V = "api-version=2016-11-01"


def main():
    c = config()
    g = requests.Session()
    g.headers["Authorization"] = f"Bearer {token('graph')}"
    items_url = f"https://graph.microsoft.com/v1.0/sites/{c['site_id']}/lists/{c['lists']['IT Tickets']}/items"
    items = {i["fields"]["Title"]: i["id"] for i in g.get(f"{items_url}?$expand=fields&$top=50").json()["value"]}
    now = datetime.now(timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")

    def patch(ticket, fields):
        r = g.patch(f"{items_url}/{items[ticket]}/fields", json=fields)
        r.raise_for_status()
        print(f"{ticket}: {list(fields)}")

    patch("INC-00003", {"Status": "Resolved",
                        "ResolutionNotes": "Restarted the print spooler on the 3rd-floor print server and cleared the stuck queue. "
                                           "Test print confirmed by requester."})
    patch("INC-00002", {"WarnAt": iso(now - timedelta(minutes=1)), "Status": "In Progress",
                        "ResolutionNotes": f"TEST: warning time moved to {iso(now)} to exercise the SLA warning."})
    patch("INC-00001", {"SlaDueAt": iso(now - timedelta(minutes=1)), "WarnSent": True,
                        "ResolutionNotes": f"TEST: SLA due time moved to {iso(now)} to exercise the breach escalation."})

    f = requests.Session()
    f.headers["Authorization"] = f"Bearer {token('flow')}"
    base = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{c['environment']}/flows"
    for name, trig in [("Desk - SLA watch", "Every_15_minutes"), ("Desk - Daily digest", "Every_day_at_8am")]:
        r = f.post(f"{base}/{c['flows'][name]}/triggers/{trig}/run?{V}")
        print(f"run {name}: {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    main()
