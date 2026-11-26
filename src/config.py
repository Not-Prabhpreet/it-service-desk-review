"""Shared paths and analysis settings. Every script imports from here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
RAW_CSV = RAW_DIR / "incident_event_log.csv"
RAW_URL = ("https://archive.ics.uci.edu/static/public/498/"
           "incident+management+process+enriched+event+log.zip")
CLEAN_DIR = ROOT / "data" / "clean"
DOCS_DIR = ROOT / "docs"
FIG_DIR = DOCS_DIR / "figures"
REPORTS_DIR = ROOT / "reports"
POWERBI_DIR = ROOT / "powerbi"
METRICS_JSON = CLEAN_DIR / "metrics.json"

# Reporting window: the three full months that hold 98% of the incidents.
# Everything outside it is a one-day stub (29 Feb) or a thin tail (Jun 2016 - Feb 2017).
WINDOW_START = "2016-03-01"
WINDOW_END = "2016-05-31"   # inclusive, by opened date

# Colors (validated reference palette, light mode)
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#b4b2ab"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e4df"
