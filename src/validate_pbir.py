"""Validate every PBIR/PBIP JSON file against Microsoft's published JSON schemas.

Schemas are fetched from github.com/microsoft/json-schemas on first use and cached in
~/.cache/pbir-schemas. Exit code 1 if any file fails.
"""
import json
import sys
import urllib.request
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource

from config import POWERBI_DIR

PREFIX = "https://developer.microsoft.com/json-schemas/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"
CACHE = Path.home() / ".cache" / "pbir-schemas"


def fetch(uri):
    rel = uri.split("#")[0].replace(PREFIX, "")
    local = CACHE / rel
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(RAW + rel) as r:
            local.write_bytes(r.read())
    return json.loads(local.read_text(encoding="utf-8"))


def retrieve(uri):
    return Resource.from_contents(fetch(uri))


def main():
    registry = Registry(retrieve=retrieve)
    files = [p for p in POWERBI_DIR.rglob("*") if p.suffix in (".json", ".pbir", ".pbism", ".pbip")
             and "StaticResources" not in p.parts and ".pbi" not in p.parts]
    bad = 0
    for p in files:
        doc = json.loads(p.read_text(encoding="utf-8"))
        uri = doc.get("$schema")
        if not uri or "gitIntegration" in uri:
            continue
        schema = fetch(uri)
        errs = sorted(Draft7Validator(schema, registry=registry).iter_errors(doc), key=lambda e: list(e.path))
        for e in errs[:5]:
            bad += 1
            print(f"FAIL {p.relative_to(POWERBI_DIR)}: {'/'.join(map(str, e.path))}: {e.message[:200]}")
    print(f"validate: {len(files)} files checked, {bad} schema errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
