"""Export each desk flow as a Power Automate import package (.zip) into power-automate/packages/.

Uses the same "Export > Package (.zip)" API the Power Automate portal calls. Import elsewhere with
My flows > Import > Import package (Legacy), then map the SharePoint / Forms / Outlook connections
and point the flow at your own site, lists and form (see power-automate/README.md).
"""
import re
from pathlib import Path

import requests

from ms_auth import config, token

BAP = "https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments"
V = "api-version=2016-11-01"
OUT = Path(__file__).resolve().parents[1] / "packages"


def main():
    c = config()
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token('powerapps')}"
    env = c["environment"]
    OUT.mkdir(exist_ok=True)
    for name, fid in c["flows"].items():
        r = s.post(f"{BAP}/{env}/listPackageResources?{V}",
                   json={"baseResourceIds": [f"/providers/Microsoft.Flow/flows/{fid}"]})
        r.raise_for_status()
        resources = r.json()["resources"]
        for res in resources.values():
            if res["type"] == "Microsoft.Flow/flows":
                res["suggestedCreationType"] = "New"      # import creates a new flow
            elif res["type"] == "Microsoft.PowerApps/apis/connections":
                res["suggestedCreationType"] = "Existing"  # importer picks their own connection
        body = {"details": {
            "displayName": name, "description": "IT service desk demo flow (exported by scripts/export_packages.py)",
            "creator": "IT Service Desk Performance & Problem Review", "sourceEnvironment": env},
            "resources": resources, "includedResourceIds": [r["id"] for r in resources.values()]}
        r = s.post(f"{BAP}/{env}/exportPackage?{V}", json=body)
        r.raise_for_status()
        link = r.json()["packageLink"]["value"]
        fname = OUT / (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".zip")
        fname.write_bytes(requests.get(link).content)
        print(f"exported {name} -> {fname.name} ({fname.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
