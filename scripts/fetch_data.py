#!/usr/bin/env python3
"""Pulls the video-campaign data and writes site/data.enc.json, encrypted with the team passcode.

Environment (GitHub secrets):
  CRM_PASSCODE        required  passcode the team types to open the CRM (use 16+ characters)
  MAKE_API_TOKEN      required  Make API token with the datastores:read scope
  MANYREACH_API_KEY   required  ManyReach API key of the Everly workspace
  MANYREACH_API_KEY_2 optional  ManyReach API key of the Animohub workspace
  CAL_API_KEY         optional  cal.com API key (starts with cal_live_) for the Meetings tab
"""
import base64, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

MAKE_ZONE = os.environ.get("MAKE_ZONE", "eu1.make.com")
STORE_REPLIES, STORE_VIEWS = 243100, 252468
MR = "https://api.manyreach.com/api/v2"
KEEP = ["status", "campaign_id", "campaign_title", "step_title", "prospect_email", "first_name", "company", "website", "job_title",
        "reply_text", "intent", "summary", "video_url", "draft_subject", "draft_body_html", "draft_preview", "instruction",
        "last_error", "created_at", "updated_at", "sent_at", "classification", "sender_email"]
TEST_INBOXES = {"ashutoshbansal0410@gmail.com"}
errors = []


def get(url, headers, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "animohub-crm", **headers})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace')}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:  # network errors
            last = repr(e)
        time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url.split('?')[0]}: {last}")


def make_store(store_id):
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"pg[limit]": 100, "pg[offset]": offset})
        r = get(f"https://{MAKE_ZONE}/api/v2/data-stores/{store_id}/data?{q}", {"Authorization": "Token " + os.environ["MAKE_API_TOKEN"]})
        recs = r.get("records", [])
        out += recs
        if len(recs) < 100:
            return out
        offset += 100


def strip_html(h):
    h = re.split(r"<div>On [^<]{5,80} wrote:</div>", h or "")[0]
    h = re.sub(r"<img[^>]*>", "", h)
    h = re.sub(r"<li[^>]*>", "- ", h)
    h = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</ul>", "\n", h)
    h = html.unescape(re.sub(r"<[^>]+>", "", h))
    h = re.sub(r"[ \t]+\n", "\n", h)
    return re.sub(r"\n{3,}", "\n\n", h).strip()


def mr_pages(path, key, params, cap=10):
    items = []
    for page in range(1, cap + 1):
        q = urllib.parse.urlencode({**params, "limit": 30, "page": page})
        r = get(f"{MR}{path}?{q}", {"X-API-Key": key})
        if isinstance(r, list):
            got, total = r, 0
        else:
            got = r.get("items") or r.get("data") or r.get("campaigns") or r.get("results") or []
            if isinstance(got, dict):
                got = got.get("items") or got.get("campaigns") or []
            total = (r.get("pagination") or r.get("meta") or {}).get("totalItems", 0)
            if page == 1 and path == "/campaigns":
                print(f"DIAG {path}: response keys={sorted(r.keys())[:8]} items_on_page={len(got)} total={total}")
        items += got
        if not got or page * 30 >= total:
            break
    return items


def manyreach(key, label):
    camps, sent = [], {}
    listed = mr_pages("/campaigns", key, {})
    video = [c for c in listed if "video lead magnet" in (c.get("name") or "").lower()]
    print(f"DIAG ManyReach {label}: {len(listed)} campaigns listed, {len(video)} named 'Video lead magnet' (tests included)")
    if listed and not video:
        errors.append(f"ManyReach ({label}): the key reaches {len(listed)} campaigns but none is named 'Video lead magnet'. It may be the wrong workspace's key.")
    for c in listed:
        name = c.get("name") or ""
        if "video lead magnet" not in name.lower() or name.lower().startswith("test"):
            continue
        cid = c["campaignId"]
        camp = {"id": cid, "name": name, "ws": label, "status": c.get("status"), "prospects": c.get("prospectCount"), "e1": 0, "e2": 0}
        try:
            st = get(f"{MR}/campaigns/{cid}/stats", {"X-API-Key": key})
            tot = sum(x or 0 for x in (st.get("sentSeries") or {}).get("count", []))
            camp["e1"] = sum(x or 0 for x in (st.get("sentInitialSeries") or {}).get("count", []))
            camp["e2"] = max(0, tot - camp["e1"])
        except Exception as e:
            camp["e1"] = c.get("sentCount") or 0
            errors.append(f"ManyReach stats for campaign {cid}: {e}")
        try:
            for m in mr_pages("/messages", key, {"type": "SentManual", "campaignId": cid}):
                e = (m.get("toEmail") or "").lower()
                sent.setdefault(e, []).append({"t": m.get("createdAt"), "body": strip_html(m.get("body")), "tag": ""})
        except Exception as e:
            errors.append(f"ManyReach sent replies for campaign {cid}: {e}")
        camps.append(camp)
    return camps, sent


def cal_bookings():
    key = os.environ.get("CAL_API_KEY")
    if not key:
        return None
    out = []
    for status in ("upcoming", "past", "cancelled"):
        r = get(f"https://api.cal.com/v2/bookings?status={status}&take=100", {"Authorization": "Bearer " + key, "cal-api-version": "2024-08-13"})
        data = r.get("data", [])
        data = data.get("bookings", []) if isinstance(data, dict) else data
        for b in data:
            out.append({"uid": b.get("uid"), "title": b.get("title"), "start": b.get("start"), "end": b.get("end"), "status": b.get("status"),
                        "url": b.get("meetingUrl") or b.get("location"),
                        "attendees": [{"name": a.get("name"), "email": a.get("email")} for a in (b.get("attendees") or [])]})
    seen, uniq = set(), []
    for b in out:
        if b["uid"] not in seen:
            seen.add(b["uid"]); uniq.append(b)
    return uniq


def encrypt(payload, passcode):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv, iters = os.urandom(16), os.urandom(12), 600000
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(passcode.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), None)
    b = lambda x: base64.b64encode(x).decode("ascii")
    return {"v": 1, "iter": iters, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "site/data.enc.json"
    passcode = os.environ.get("CRM_PASSCODE", "")
    if len(passcode) < 12:
        sys.exit("CRM_PASSCODE is missing or shorter than 12 characters.")
    if len(sys.argv) > 2:  # local test: encrypt a ready-made payload
        payload = json.load(open(sys.argv[2]))
    else:
        recs = []
        for r in make_store(STORE_REPLIES):  # a failure here stops the run, so the last good page stays up
            d = r.get("data") or {}
            if (d.get("prospect_email") or "").lower() in TEST_INBOXES:
                continue
            recs.append({"key": r.get("key"), "data": {k: d[k] for k in KEEP if d.get(k) not in (None, "", "None")}})
        try:
            views = make_store(STORE_VIEWS)
        except Exception as e:
            views = []; errors.append(f"Video watch tracker: {e}")
        camps, sent = [], {}
        for env, label in (("MANYREACH_API_KEY", "Everly"), ("MANYREACH_API_KEY_2", "Animohub")):
            if os.environ.get(env):
                try:
                    c, s = manyreach(os.environ[env], label)
                    camps += c
                    for k, v in s.items():
                        sent.setdefault(k, []).extend(v)
                except Exception as e:
                    errors.append(f"ManyReach ({label}): {e}")
        try:
            meetings = cal_bookings()
        except Exception as e:
            meetings = None; errors.append(f"cal.com: {e}")
        payload = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "recs": recs, "views": views, "camps": camps,
                   "sent": sent, "meetings": meetings, "errors": [re.sub(r"\s+", " ", x)[:200] for x in errors]}
        print(f"replies={len(recs)} views={len(views)} campaigns={len(camps)} threads={len(sent)} "
              f"meetings={'off' if meetings is None else len(meetings)} errors={len(errors)}")
        for x in errors:
            print("WARN", x[:300])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(encrypt(payload, passcode), open(out_path, "w"))


if __name__ == "__main__":
    main()
