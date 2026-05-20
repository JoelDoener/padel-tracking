"""
Padel Amigos — Availability Tracker (Multi-Venue)
Nutzt die Playtomic API direkt (kein Browser, kein Playwright).

Setup:
    pip install requests

Cron (8x pro Stunde):
    25,29,30,31,55,59 * * * * python3 /root/padel-tracking/padel_tracker.py --venue halstenbek
    25,29,30,31,55,59 * * * * python3 /root/padel-tracking/padel_tracker.py --venue jesteburg
    0,1 * * * * python3 /root/padel-tracking/padel_tracker.py --venue halstenbek
    0,1 * * * * python3 /root/padel-tracking/padel_tracker.py --venue jesteburg
"""

import argparse
import csv
import json
import requests
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VENUES = {
    "halstenbek": {
        "tenant_id": "47894b5e-7299-42b4-b3df-9a82d75e55a3",
        "courts": {
            "58480281-55d3-4964-ad4c-5b71eaf04d33": "Outdoor 1",
            "d3787f7c-7b6d-4352-a3f6-d25aeae35bad": "Outdoor 2",
            "4f754fb9-9b38-4eb0-9627-6a6161ec2ea0": "Outdoor 3",
            "177fa8ca-a395-4398-b0b8-c1c65432e515": "Outdoor 4",
            "99c89172-be8d-45ec-a1c3-fc2b173b9391": "Indoor 1",
            "e0bb5565-5fed-49bd-bb82-3ae4c70f1971": "Indoor 2",
            "61b268a4-306b-407e-a8a1-86a9d624a909": "Indoor 3",
            "01c0e205-a754-47b3-91df-5f576e938b7c": "Indoor 4",
            "c270cf89-2ce3-4e45-9a55-dff31ba1c883": "Single Indoor",
        },
    },
    "jesteburg": {
        "tenant_id": "62cb46b5-91e2-44c9-b693-299024b161b0",
        "courts": {
            "1775a96d-3c87-4e34-9ff5-c6bdb18e942c": "Padel 2",
            "7e773233-957f-4720-bb73-d3d30dfa5e62": "Padel 3",
            "197daebf-3b85-418d-92af-f316069711b2": "Padel 4",
            "ee751119-7276-413a-8e94-d75cfec7f672": "Padel 1",
        },
    },
}

SPORT_ID   = "PADEL"
DAYS_AHEAD = 14
TIMEZONE   = ZoneInfo("Europe/Berlin")
BASE_URL   = "https://playtomic.com/api/clubs/availability"


def fetch_slots(tenant_id: str, target_date: date) -> list[dict]:
    params = {"tenant_id": tenant_id, "date": target_date.isoformat(), "sport_id": SPORT_ID}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_price(price_str: str | None) -> float | None:
    if not price_str:
        return None
    try:
        return float(price_str.split()[0])
    except (ValueError, IndexError):
        return None


def build_rows(snapshot_ts: datetime, target_date: date, api_data: list, courts: dict) -> list[dict]:
    rows = []
    for court_data in api_data:
        resource_id = court_data.get("resource_id", "")
        court_name  = courts.get(resource_id, resource_id)
        for slot in court_data.get("slots", []):
            raw_time = slot.get("start_time", "")[:5]
            if raw_time:
                utc_dt   = datetime.combine(target_date,
                               datetime.strptime(raw_time, "%H:%M").time(),
                               tzinfo=timezone.utc)
                local_dt = utc_dt.astimezone(TIMEZONE)
                start_time = local_dt.strftime("%H:%M")
                slot_date  = local_dt.date()
            else:
                start_time = ""
                slot_date  = target_date
            rows.append({
                "datum_snapshot": snapshot_ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "datum_slot":     slot_date.isoformat(),
                "uhrzeit_slot":   start_time,
                "dauer_minuten":  slot.get("duration"),
                "court":          court_name,
                "preis":          parse_price(slot.get("price")),
                "status":         "frei",
                "tage_im_voraus": (slot_date - snapshot_ts.date()).days,
            })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["datum_snapshot", "datum_slot", "uhrzeit_slot",
                  "dauer_minuten", "court", "preis", "status", "tage_im_voraus"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {len(rows)} Zeilen → {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--venue", required=True, choices=list(VENUES.keys()))
    args = parser.parse_args()

    venue_cfg  = VENUES[args.venue]
    tenant_id  = venue_cfg["tenant_id"]
    courts     = venue_cfg["courts"]
    output_dir = Path("/root/padel-tracking") / args.venue / "snapshots"

    snapshot_ts = datetime.now(tz=TIMEZONE)
    output_path = output_dir / snapshot_ts.strftime("snapshot_%Y-%m-%d_%H%M.csv")

    print(f"\nPadel Tracker [{args.venue}] — {snapshot_ts.strftime('%Y-%m-%d %H:%M')} Uhr")
    print(f"Scanne {DAYS_AHEAD + 1} Tage ({date.today()} bis {date.today() + timedelta(days=DAYS_AHEAD)})\n")

    all_rows, errors = [], []

    for i in range(DAYS_AHEAD + 1):
        target_date = date.today() + timedelta(days=i)
        try:
            api_data = fetch_slots(tenant_id, target_date)
            rows     = build_rows(snapshot_ts, target_date, api_data, courts)
            all_rows.extend(rows)
            slot_count = sum(len(c.get("slots", [])) for c in api_data)
            print(f"  Tag +{i:02d}  {target_date}  →  {slot_count} freie Slots ({len(api_data)} Courts)")
        except Exception as e:
            print(f"  Tag +{i:02d}  {target_date}  →  FEHLER: {e}")
            errors.append({"date": target_date.isoformat(), "error": str(e)})

    write_csv(all_rows, output_path)

    if errors:
        err_path = output_dir / f"errors_{snapshot_ts.strftime('%Y-%m-%d_%H%M')}.json"
        err_path.write_text(json.dumps(errors, indent=2))
        print(f"\n  ⚠ {len(errors)} Fehler → {err_path}")

    print(f"\nFertig. {len(all_rows)} Zeilen gesamt.\n")


if __name__ == "__main__":
    main()
