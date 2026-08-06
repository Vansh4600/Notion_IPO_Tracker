import urllib.request
import re
import json
import sys
import os
from datetime import datetime

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
if not NOTION_TOKEN:
    print("Error: NOTION_TOKEN environment variable not set", file=sys.stderr)
    sys.exit(1)

DATABASE_ID = "39e7979f-38f6-80fa-a617-f2b6790e1499"
TODAY = datetime.now().strftime("%Y-%m-%d")

def notion_api(method, endpoint, payload=None):
    url = f"https://api.notion.com/v1/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url, method=method, data=data,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))

def get_gmp_data():
    """Scrape IPOWatch for GMP data of all IPOs."""
    url = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        print(f"  Error fetching GMP data: {e}", file=sys.stderr)
        return {}

    gmp_map = {}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if cells and len(cells) >= 6:
            cleaned = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            ipo_name = cleaned[0].strip()
            gmp_val = cleaned[1].strip()      # e.g. "₹170"
            trend = cleaned[2].strip()         # e.g. "🟢"
            price = cleaned[3].strip()         # e.g. "₹807"
            est_listing = cleaned[4].strip()   # e.g. "₹977 (21.06%)"
            dates = cleaned[5].strip()         # e.g. "10-12 August"
            gmp_map[ipo_name] = {
                "gmp": gmp_val,
                "trend": trend,
                "price": price,
                "est_listing": est_listing,
                "dates": dates
            }
    return gmp_map

def get_mainboard_ipos():
    """Scrape Chittorgarh for upcoming + active mainboard IPOs with slugs."""
    url = "https://www.chittorgarh.com/report/ipo-in-india-list-main-board-sme/82/mainboard/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8")

    paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
    ipos = []
    for p in paras:
        if any(k in p for k in ["upcoming mainboard", "current mainboard"]):
            links = re.findall(r"href=\"https://www\.chittorgarh\.com/ipo/([^\"]+)\"[^>]*title=\"([^\"]+)\"", p)
            for slug, title in links:
                name = title.replace(" IPO", "").strip()
                slug = slug.rstrip("/")
                if name not in [i["name"] for i in ipos]:
                    ipos.append({"name": name, "slug": slug})
    return ipos

def get_ipo_dates(slug):
    """Scrape individual IPO page for open/close dates."""
    url = f"https://www.chittorgarh.com/ipo/{slug}/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        print(f"  Error fetching {slug}: {e}", file=sys.stderr)
        return None, None

    open_date = close_date = None
    open_match = re.search(r"IPO\s*(?:<!--\s*-->\s*)?Open\s*</a>.*?text-end[^>]*>([^<]+)<", html, re.DOTALL)
    close_match = re.search(r"IPO\s*(?:<!--\s*-->\s*)?Close\s*</a>.*?text-end[^>]*>([^<]+)<", html, re.DOTALL)
    if open_match:
        open_date = parse_date(open_match.group(1).strip())
    if close_match:
        close_date = parse_date(close_match.group(1).strip())
    return open_date, close_date

def parse_date(date_str):
    for fmt in ["%a, %b %d, %Y", "%b %d, %Y", "%a, %B %d, %Y", "%B %d, %Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def determine_status(open_date, close_date):
    if not open_date or not close_date:
        return "Upcoming"
    today = datetime.strptime(TODAY, "%Y-%m-%d")
    open_dt = datetime.strptime(open_date, "%Y-%m-%d")
    close_dt = datetime.strptime(close_date, "%Y-%m-%d")
    if today < open_dt:
        return "Upcoming"
    elif open_dt <= today <= close_dt:
        return "Active - Apply Now"
    else:
        return "Closed"

def match_gmp(ipo_name, gmp_map):
    """Fuzzy match IPO name with GMP data."""
    # Try direct match first
    for gmp_name, data in gmp_map.items():
        if ipo_name.lower() in gmp_name.lower() or gmp_name.lower() in ipo_name.lower():
            return data
    # Try first word match
    first_word = ipo_name.split()[0].lower()
    for gmp_name, data in gmp_map.items():
        if first_word in gmp_name.lower():
            return data
    return None

def get_existing_notion_ipos():
    result = notion_api("POST", f"databases/{DATABASE_ID}/query", {"page_size": 100})
    existing = {}
    for page in result.get("results", []):
        props = page.get("properties", {})
        title_list = props.get("Company Name", {}).get("title", [])
        if title_list:
            title = title_list[0].get("text", {}).get("content", "").strip()
            base_name = title.replace(" IPO", "").strip()
            existing[base_name] = page["id"]
    return existing

def add_ipo_to_notion(ipo):
    name = ipo["name"]
    status = ipo["status"]
    open_date = ipo["open_date"]
    close_date = ipo["close_date"]
    gmp = ipo.get("gmp_data")

    gmp_str = gmp["gmp"] if gmp else "N/A"
    price_str = gmp["price"] if gmp else "N/A"
    est_listing_str = gmp["est_listing"] if gmp else "N/A"
    trend_str = gmp["trend"] if gmp else ""

    tags = [{"name": "Mainboard"}, {"name": status}]

    properties = {
        "Company Name": {"title": [{"text": {"content": f"{name} IPO"}}]},
        "Tags": {"multi_select": tags},
        "GMP": {"rich_text": [{"text": {"content": f"{gmp_str} {trend_str}".strip()}}]},
        "Expected Listing": {"rich_text": [{"text": {"content": est_listing_str}}]}
    }
    if close_date:
        properties["Last Date"] = {"date": {"start": close_date}}

    children = [
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📊 {name} IPO"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🏷️ Status: {status}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📅 Open Date: {open_date or 'TBA'}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"⏰ Last Date to Apply: {close_date or 'TBA'}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"💰 Price Band: {price_str}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📈 GMP (Grey Market Premium): {gmp_str} {trend_str}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🎯 Expected Listing Price: {est_listing_str}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🔗 https://www.chittorgarh.com/ipo/"}}]}},
    ]

    try:
        return notion_api("POST", "pages", {"parent": {"database_id": DATABASE_ID}, "properties": properties, "children": children})
    except Exception as e:
        print(f"  Error adding {name}: {e}", file=sys.stderr)
        # Retry without children
        try:
            return notion_api("POST", "pages", {"parent": {"database_id": DATABASE_ID}, "properties": properties})
        except Exception as e2:
            print(f"  Retry also failed: {e2}", file=sys.stderr)
            return None

def update_ipo_in_notion(page_id, ipo):
    status = ipo["status"]
    close_date = ipo["close_date"]
    gmp = ipo.get("gmp_data")
    gmp_str = gmp["gmp"] if gmp else "N/A"
    trend_str = gmp["trend"] if gmp else ""
    price_str = gmp["price"] if gmp else "N/A"
    est_listing_str = gmp["est_listing"] if gmp else "N/A"

    tags = [{"name": "Mainboard"}, {"name": status}]

    properties = {
        "Tags": {"multi_select": tags},
        "GMP": {"rich_text": [{"text": {"content": f"{gmp_str} {trend_str}".strip()}}]},
        "Expected Listing": {"rich_text": [{"text": {"content": est_listing_str}}]}
    }
    if close_date:
        properties["Last Date"] = {"date": {"start": close_date}}

    notion_api("PATCH", f"pages/{page_id}", {"properties": properties})

    # Also update page content with latest GMP

    children = [
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📊 {ipo['name']} IPO — Updated {datetime.now().strftime('%d %b %Y %H:%M')}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🏷️ Status: {status}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📅 Open: {ipo['open_date'] or 'TBA'} | Close: {close_date or 'TBA'}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"💰 Price Band: {price_str}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📈 GMP: {gmp_str} {trend_str}"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🎯 Expected Listing: {est_listing_str}"}}]}},
    ]
    try:
        notion_api("PATCH", f"blocks/{page_id}/children", {"children": children})
    except Exception as e:
        print(f"  Error updating content for {ipo['name']}: {e}", file=sys.stderr)

def main():
    print(f"🔍 IPO Checker running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Today: {TODAY}")
    print("-" * 60)

    # Step 1: Get GMP data
    print("📈 Fetching GMP data from IPOWatch...")
    gmp_map = get_gmp_data()
    print(f"   Found GMP for {len(gmp_map)} IPOs")

    # Step 2: Get mainboard IPOs
    print("📋 Fetching mainboard IPOs from Chittorgarh...")
    ipos = get_mainboard_ipos()
    if not ipos:
        print("❌ No IPOs parsed.")
        return
    print(f"   Found {len(ipos)} mainboard IPOs")

    # Step 3: Enrich with dates + GMP
    print("\n🔄 Enriching with dates & GMP...")
    for ipo in ipos:
        open_date, close_date = get_ipo_dates(ipo["slug"])
        ipo["open_date"] = open_date
        ipo["close_date"] = close_date
        ipo["status"] = determine_status(open_date, close_date)
        ipo["gmp_data"] = match_gmp(ipo["name"], gmp_map)

        gmp_str = ipo["gmp_data"]["gmp"] if ipo["gmp_data"] else "N/A"
        trend = ipo["gmp_data"]["trend"] if ipo["gmp_data"] else ""
        print(f"   {ipo['name']}: Close={close_date} | GMP={gmp_str} {trend} | {ipo['status']}")

    # Step 4: Sync to Notion
    print(f"\n📝 Syncing to Notion...")
    existing = get_existing_notion_ipos()
    print(f"   {len(existing)} existing entries")
    print("-" * 60)

    new_added = updated = 0
    for ipo in ipos:
        if ipo["name"] in existing:
            update_ipo_in_notion(existing[ipo["name"]], ipo)
            print(f"🔄 Updated: {ipo['name']}")
            updated += 1
        else:
            add_ipo_to_notion(ipo)
            print(f"✅ NEW: {ipo['name']} IPO")
            new_added += 1

    print("-" * 60)
    print(f"📊 Summary: {new_added} new, {updated} updated")

    # Print active IPOs
    active = [i for i in ipos if "Active" in i["status"]]
    if active:
        print(f"\n🟢 APPLY NOW:")
        for i in active:
            g = i.get("gmp_data", {}) or {}
            print(f"   → {i['name']} IPO | Last Date: {i['close_date']} | GMP: {g.get('gmp','N/A')} | Est Listing: {g.get('est_listing','N/A')}")

    upcoming = [i for i in ipos if i["status"] == "Upcoming"]
    if upcoming:
        print(f"\n🔜 UPCOMING:")
        for i in upcoming:
            g = i.get("gmp_data", {}) or {}
            print(f"   → {i['name']} IPO | Opens: {i['open_date']} | GMP: {g.get('gmp','N/A')} | Est Listing: {g.get('est_listing','N/A')}")

if __name__ == "__main__":
    main()
