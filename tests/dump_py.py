"""Dump Python-engine lookups for the parity test dates."""
import json, sys
sys.path.insert(0, ".")
from navigator import apply as ap
print(json.dumps({d: ap.run(d)["lookups"] for d in ["2025-12-31", "2026-01-02", "2026-10-01", "2027-07-02"]}, ensure_ascii=False))
