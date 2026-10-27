#!/usr/bin/env python3
"""
Adds Drupal node URLs + thumbnail URLs to pics60.json.

For each feature:
  1. Follow the old Islandora URL's redirect to find the Drupal node ID.
  2. Fetch https://digital.lib.uiowa.edu/node/<id>/iiif-p/manifest
  3. Pull a thumbnail URL out of the IIIF manifest.
Writes pics60_fixed.json with new properties: NODEURL, THUMB.
Results are cached in idl_cache.json, so you can stop and re-run safely.

Usage:   python fix_pics60.py pics60.json pics60_fixed.json
Needs:   Python 3.8+, no extra packages.
"""
import json, re, sys, time, urllib.request, urllib.error

SRC = sys.argv[1] if len(sys.argv) > 1 else "pics60.json"
DST = sys.argv[2] if len(sys.argv) > 2 else "pics60_fixed.json"
CACHE_FILE = "idl_cache.json"
DELAY = 0.5  # seconds between requests; be polite to the server
HEADERS = {"User-Agent": "Mozilla/5.0 (map-link-fixer)", "Accept": "*/*"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def find_node_id(old_url):
    final_url, html = get(old_url)
    m = re.search(r"/node/(\d+)", final_url)
    if m:
        return m.group(1)
    # Drupal pages usually advertise their node in a shortlink/canonical tag
    m = re.search(r'rel="(?:shortlink|canonical)"[^>]*href="[^"]*?/node/(\d+)"', html) \
        or re.search(r'href="[^"]*?/node/(\d+)"[^>]*rel="(?:shortlink|canonical)"', html)
    return m.group(1) if m else None


def _id(x):
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return x.get("@id") or x.get("id")
    if isinstance(x, list) and x:
        return _id(x[0])
    return None


def find_thumb(manifest):
    # 1. manifest-level thumbnail
    t = _id(manifest.get("thumbnail"))
    if t:
        return t
    # 2. first canvas thumbnail (IIIF 2 and 3)
    canvases = manifest.get("items") or []
    for seq in manifest.get("sequences", []):
        canvases = canvases or seq.get("canvases", [])
    if canvases:
        c = canvases[0]
        t = _id(c.get("thumbnail"))
        if t:
            return t
        # 3. build one from the image service
        for img in c.get("images", []):
            svc = (img.get("resource") or {}).get("service") or {}
            if svc.get("@id"):
                return svc["@id"].rstrip("/") + "/full/200,/0/default.jpg"
    return None


def main():
    try:
        cache = json.load(open(CACHE_FILE))
    except Exception:
        cache = {}

    raw = open(SRC, encoding="utf-8-sig").read()
    data = json.loads(raw)
    feats = data["features"]
    failed = []

    for i, f in enumerate(feats, 1):
        old = f["properties"]["URL"]
        if old in cache and cache[old].get("thumb"):
            entry = cache[old]
        else:
            entry = {}
            try:
                node = find_node_id(old)
                time.sleep(DELAY)
                if node:
                    entry["node"] = node
                    _, body = get(f"https://digital.lib.uiowa.edu/node/{node}/iiif-p/manifest")
                    entry["thumb"] = find_thumb(json.loads(body))
                    time.sleep(DELAY)
            except (urllib.error.URLError, ValueError) as e:
                entry["error"] = str(e)
            cache[old] = entry
            json.dump(cache, open(CACHE_FILE, "w"), indent=1)
        print(f"[{i}/{len(feats)}] {old} -> {entry}")
        if entry.get("node"):
            f["properties"]["NODEURL"] = f"https://digital.lib.uiowa.edu/node/{entry['node']}"
        if entry.get("thumb"):
            f["properties"]["THUMB"] = entry["thumb"]
        else:
            failed.append(old)

    # same layout as the original: one feature per line
    with open(DST, "w", encoding="utf-8") as out:
        out.write('{\n    "type": "FeatureCollection",\n    "features" : [\n')
        out.write(",\n".join(json.dumps(f, separators=(",", ":"), ensure_ascii=False) for f in feats))
        out.write("\n]\n}\n")

    print(f"\nDone. {len(feats) - len(failed)} ok, {len(failed)} without a thumbnail.")
    for u in failed:
        print("  FAILED:", u)


if __name__ == "__main__":
    main()
