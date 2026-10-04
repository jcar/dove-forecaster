#!/usr/bin/env python3
"""Put the currently published site data back into docs/ when today's
location build fails.

docs/ is no longer committed (D23): the site is deployed straight from the
daily job. That removes git as the place yesterday's forecasts were kept, so
a failed build would otherwise deploy a page with no locations at all. This
copies what is live now, so a bad morning serves yesterday rather than nothing.
"""
import json, os, sys
import requests

SITE = os.environ.get("SITE_URL", "https://jcar.github.io/dove-forecaster")
OUT = "docs/data"


def get(path):
    r = requests.get(f"{SITE}/data/{path}", timeout=60)
    r.raise_for_status()
    os.makedirs(os.path.dirname(f"{OUT}/{path}") or OUT, exist_ok=True)
    open(f"{OUT}/{path}", "wb").write(r.content)
    return r.content


def main():
    idx = json.loads(get("index.json"))
    get("flow.json")
    ok = 0
    for s in idx["sites"]:
        try:
            get(f"loc/{s['id']}.json"); ok += 1
        except Exception as ex:
            print(f"  {s['id']}: {type(ex).__name__}")
    print(f"restored {ok}/{len(idx['sites'])} locations from {SITE}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
