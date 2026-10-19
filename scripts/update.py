#!/usr/bin/env python3
"""Pull Toronto business licence data and write docs/data.json with recently issued food licences."""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

CKAN = "https://ckan0.cf.opendata.inter.prod-toronto.ca"
PACKAGE_ID = os.environ.get("PACKAGE_ID", "municipal-licensing-and-standards-business-licences-and-permits")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "120"))
KEYWORDS = [k.strip().upper() for k in os.environ.get(
    "CATEGORY_KEYWORDS", "EATING ESTABLISHMENT,TAKE-OUT OR RETAIL FOOD,RESTAURANT").split(",")]
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "new-toronto-restaurants/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def norm(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def pick(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


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


def find_resource(pkg):
    res = [r for r in pkg["result"]["resources"] if r.get("datastore_active")]
    if not res:
        sys.exit("No datastore resource found in package %s" % PACKAGE_ID)
    for r in res:
        if any(w in r["name"].lower() for w in ("licence", "license", "business")):
            return r
    return res[0]


def fetch_rows(resource_id):
    offset, limit = 0, 10000
    while True:
        q = urllib.parse.urlencode({"resource_id": resource_id, "limit": limit, "offset": offset})
        res = get_json("%s/api/3/action/datastore_search?%s" % (CKAN, q))["result"]
        recs = res["records"]
        for rec in recs:
            yield {norm(k): v for k, v in rec.items()}
        offset += limit
        if offset >= res["total"] or not recs:
            break


def main():
    pkg = get_json("%s/api/3/action/package_show?id=%s" % (CKAN, PACKAGE_ID))
    resource = find_resource(pkg)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)
    seen, out = set(), []

    for row in fetch_rows(resource["id"]):
        category = pick(row, "category", "licencecategory")
        if not any(k in category.upper() for k in KEYWORDS):
            continue
        issued = parse_date(pick(row, "issued", "issueddate", "licenceissueddate"))
        if not issued or issued < cutoff:
            continue
        if parse_date(pick(row, "canceldate", "cancelleddate")):
            continue  # skip cancelled licences
        lic_no = pick(row, "licenceno", "licenseno", "licencenumber")
        if lic_no and lic_no in seen:
            continue
        seen.add(lic_no)
        address = ", ".join(a for a in (
            pick(row, "licenceaddressline1"), pick(row, "licenceaddressline2"),
            pick(row, "licenceaddressline3")) if a) or pick(row, "address")
        out.append({
            "name": pick(row, "operatingname", "businessname", "clientname"),
            "address": address,
            "category": category,
            "issued": issued.isoformat(),
            "licence_no": lic_no,
        })

    out.sort(key=lambda r: r["issued"], reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "%s (resource: %s)" % (PACKAGE_ID, resource["name"]),
        "lookback_days": LOOKBACK_DAYS,
        "count": len(out),
        "records": out,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1)
    print("Wrote %d records" % len(out))


if __name__ == "__main__":
    main()
