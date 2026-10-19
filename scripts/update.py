#!/usr/bin/env python3
"""Pull Toronto business licence data and write docs/data.json with recently issued food licences.

Self-diagnosing: it hunts for a usable licence dataset, and writes a "debug" block into
data.json (fields found, top categories) so problems are easy to spot.
"""
import csv, io, itertools, json, os, re, sys, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

CKAN = "https://ckan0.cf.opendata.inter.prod-toronto.ca"
PACKAGE_ID = os.environ.get("PACKAGE_ID", "municipal-licensing-and-standards-business-licences-and-permits")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "120"))
INCLUDE = [k.strip().upper() for k in os.environ.get(
    "CATEGORY_KEYWORDS", "EATING OR DRINKING,EATING ESTABLISHMENT,TAKE-OUT,RETAIL FOOD,RESTAURANT,FOOD").split(",")]
EXCLUDE = ["MOBILE", "VEHICLE", "CART", "TRUCK", "MANUFACTUR"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "data.json")
UA = {"User-Agent": "new-toronto-restaurants/1.1"}


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r)


def norm(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def parse_date(v):
    if v in (None, ""):
        return None
    s = str(v).strip()
    try:
        if s.isdigit() and int(s) > 10**11:  # epoch milliseconds
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).date()
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


def datastore_rows(resource_id):
    offset, limit = 0, 10000
    while True:
        q = urllib.parse.urlencode({"resource_id": resource_id, "limit": limit, "offset": offset})
        res = get_json("%s/api/3/action/datastore_search?%s" % (CKAN, q))["result"]
        for rec in res["records"]:
            yield {norm(k): v for k, v in rec.items()}
        offset += limit
        if offset >= res["total"] or not res["records"]:
            break


def csv_rows(url):
    resp = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300)
    for rec in csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8-sig", newline="")):
        yield {norm(k): v for k, v in rec.items()}


def candidate_package_ids():
    ids = [PACKAGE_ID]
    try:
        q = urllib.parse.urlencode({"q": "business licences", "rows": 20})
        for p in get_json("%s/api/3/action/package_search?%s" % (CKAN, q))["result"]["results"]:
            if "licen" in p["name"] and p["name"] not in ids:
                ids.append(p["name"])
    except Exception as e:
        print("package_search failed:", e)
    return ids


def find_source():
    """Return (package_id, resource_name, row_iterator) for the first licence-like table."""
    for pid in candidate_package_ids():
        try:
            pkg = get_json("%s/api/3/action/package_show?id=%s" % (CKAN, pid))["result"]
        except Exception as e:
            print("Skipping package %s: %s" % (pid, e))
            continue
        resources = sorted(pkg.get("resources", []), key=lambda r: not r.get("datastore_active"))
        for r in resources:
            try:
                if r.get("datastore_active"):
                    it = datastore_rows(r["id"])
                elif str(r.get("format", "")).upper() == "CSV":
                    it = csv_rows(r["url"])
                else:
                    continue
                first = next(it, None)
            except Exception as e:
                print("Skipping resource %s: %s" % (r.get("name"), e))
                continue
            if first and any("category" in k for k in first) and any("name" in k for k in first):
                print("Using package=%s resource=%s" % (pid, r.get("name")))
                return pid, r.get("name", ""), itertools.chain([first], it)
            print("Resource %s does not look like licences, skipping" % r.get("name"))
    sys.exit("Could not find a usable business licence table. Check PACKAGE_ID in scripts/update.py.")


def build_map(keys):
    def find(*opts):
        for opt in opts:
            for k in keys:
                if opt in k:
                    return k
        return None
    addr = [k for k in keys if "address" in k and "licence" in k] or [k for k in keys if "address" in k]
    return {
        "name": find("operatingname", "businessname", "tradename", "clientname"),
        "category": find("category", "licencetype"),
        "issued": find("issued"),
        "cancel": find("cancel"),
        "licno": find("licenceno", "licenseno", "licencenumber"),
        "addr": sorted(addr)[:3],
    }


def is_food(category):
    c = category.upper()
    return any(k in c for k in INCLUDE) and not any(x in c for x in EXCLUDE)


def process(rows, today=None):
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    m, fields = None, []
    scanned, seen, out = 0, set(), []
    cats, newest = Counter(), None
    for row in rows:
        if m is None:
            fields = sorted(row.keys())
            m = build_map(fields)
        scanned += 1
        category = str(row.get(m["category"]) or "").strip()
        cats[category] += 1
        if not is_food(category):
            continue
        issued = parse_date(row.get(m["issued"])) if m["issued"] else None
        if issued and (newest is None or issued > newest):
            newest = issued
        if not issued or issued < cutoff:
            continue
        if m["cancel"] and parse_date(row.get(m["cancel"])):
            continue
        lic = str(row.get(m["licno"]) or "").strip() if m["licno"] else ""
        if lic and lic in seen:
            continue
        seen.add(lic)
        out.append({
            "name": str(row.get(m["name"]) or "").strip(),
            "address": ", ".join(str(row[a]).strip() for a in m["addr"] if row.get(a)),
            "category": category,
            "issued": issued.isoformat(),
            "licence_no": lic,
        })
    out.sort(key=lambda r: r["issued"], reverse=True)
    debug = {
        "rows_scanned": scanned,
        "fields": fields,
        "field_map": m,
        "newest_food_issue_date": newest.isoformat() if newest else None,
        "top_categories": cats.most_common(30),
    }
    return out, debug


def main():
    pid, rname, rows = find_source()
    out, debug = process(rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "%s (resource: %s)" % (pid, rname),
        "lookback_days": LOOKBACK_DAYS,
        "count": len(out),
        "debug": debug,
        "records": out,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1)
    print("Scanned %d rows, wrote %d records" % (debug["rows_scanned"], len(out)))


if __name__ == "__main__":
    main()
