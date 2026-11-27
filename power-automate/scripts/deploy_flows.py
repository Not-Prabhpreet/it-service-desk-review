"""Create or update the 4 desk flows through the Power Automate API (idempotent, matched by display name).

Also writes each definition to power-automate/flows/<name>.json so the logic is reviewable in git.
Needs one connection per connector (SharePoint, Microsoft Forms, Office 365 Outlook) in the environment;
it lists what's missing and stops if any are absent.
"""
import json
import sys
from pathlib import Path

import requests

from flow_definitions import API, CONNECTORS, FLOWS
from ms_auth import config, token

BASE = "https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments"
V = "api-version=2016-11-01"
OUT = Path(__file__).resolve().parents[1] / "flows"


def connections(env):
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token('powerapps')}"
    found = {}
    for key, api in CONNECTORS.items():
        r = s.get(f"https://api.powerapps.com/providers/Microsoft.PowerApps/apis/{api}/connections"
                  f"?{V}&$filter=environment eq '{env}'")
        r.raise_for_status()
        ok = [c for c in r.json().get("value", [])
              if any(st.get("status") == "Connected" for st in c["properties"].get("statuses", []))]
        if ok:
            found[key] = ok[0]["name"]
    return found


def main():
    cfg = config()
    env = cfg["environment"]
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token('flow')}"
    conns = connections(env)
    missing = [CONNECTORS[k] for k in CONNECTORS if k not in conns]
    if missing:
        sys.exit(f"Missing connections: {missing}. Create them in Power Automate > Connections, then rerun.")
    existing = {f["properties"]["displayName"]: f["name"]
                for f in s.get(f"{BASE}/{env}/flows?{V}").json().get("value", [])}
    OUT.mkdir(exist_ok=True)
    ids = {}
    for name, (builder, needs) in FLOWS.items():
        definition = builder(cfg)
        (OUT / f"{name.replace('Desk - ', '').replace(' ', '_').lower()}.json").write_text(json.dumps(definition, indent=2))
        refs = {CONNECTORS[k]: {"connectionName": conns[k], "id": API + CONNECTORS[k], "source": "Invoker"} for k in needs}
        body = {"properties": {"displayName": name, "definition": definition,
                               "connectionReferences": refs, "state": "Started"}}
        if name in existing:
            r = s.patch(f"{BASE}/{env}/flows/{existing[name]}?{V}", json=body)
            action = "updated"
        else:
            r = s.post(f"{BASE}/{env}/flows?{V}", json=body)
            action = "created"
        if not r.ok:
            print(f"FAILED {name}: {r.status_code} {r.text[:1500]}")
            continue
        ids[name] = r.json()["name"]
        print(f"{action}: {name} ({ids[name]})")
    cfg = config()
    cfg["flows"] = ids
    from ms_auth import save_config
    save_config(cfg)


if __name__ == "__main__":
    main()
