"""
Padel Amigos Hamburg — Availability Tracker
Nutzt die Playtomic API direkt (kein Browser, kein Playwright).
Läuft täglich per Cron oder GitHub Actions.

Setup:
    pip install requests

Cron (alle 30 min, 5 vor):
    25,55 * * * * python3 /path/to/padel_tracker.py
"""

import csv
import json
import os
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Konfiguration ────────────────────────────────────────────────────────────

TENANT_ID  = "47894b5e-7299-42b4-b3df-9a82d75e55a3"
SPORT_ID   = "PADEL"
DAYS_AHEAD = 14
TIMEZONE   = ZoneInfo("Europe/Berlin")
BASE_URL   = "https://playtomic.com/api/clubs/availability"

# Mapping resource_id → Court-Name (Reihenfolge = API-Reihenfolge)
COURTS = {
    "e0bb5565-5fed-49bd-bb82-3ae4c70f1971": "Outdoor 1",
    "d3787f7c-7b6d-4352-a3f6-d25aeae35bad": "Outdoor 2",
    "177fa8ca-a395-4398-b0b8-c1c65432e515": "Outdoor 3",
    "99c89172-be8d-45ec-a1c3-fc2b173b9391": "Outdoor 4",
    "4f754fb9-9b38-4eb0-9627-6a6161ec2ea0": "Indoor 1",
    "58480281-55d3-4964-ad4c-5b71eaf04d33": "Indoor 2",
    "01c0e205-a754-47b3-91df-5f576e938b7c": "Indoor 3",
    "c270cf89-2ce3-4e45-9a55-dff31ba1c883": "Indoor 4",
    "61b268a4-306b-407e-a8a1-86a9d624a909": "Single Indoor",
}

# Output-Ordner (lokal oder im Repo für GitHub Actions)
OUTPUT_DIR = Path(os.getenv("PADEL_OUTPUT_DIR", 
                  Path.home() / "Documents" / "Padel-Tracking" / "snapshots"))

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def fetch_slots(target_date: date) -> list[dict]:
    """Holt alle freien Slots für einen Tag von der Playtomic API."""
    params = {
        "tenant_id": TENANT_ID,
        "date": target_date.isoformat(),
        "sport_id": SPORT_ID,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_price(price_str: str | None) -> float | None:
    """Extrahiert float aus '30 EUR' → 30.0"""
    if not price_str:
        return None
    try:
        return float(price_str.split()[0])
    except (ValueError, IndexError):
        return None


def build_rows(snapshot_ts: datetime, target_date: date, api_data: list) -> list[dict]:
    """Konvertiert API-Antwort in CSV-Zeilen."""
    rows = []
    for court_data in api_data:
        resource_id = court_data.get("resource_id", "")
        court_name  = COURTS.get(resource_id, resource_id)  # Fallback: UUID

        for slot in court_data.get("slots", []):
            raw_time = slot.get("start_time", "")[:5]
            if raw_time:
                from datetime import timezone
                utc_dt = datetime.combine(target_date,
                             datetime.strptime(raw_time, "%H:%M").time(),
                             tzinfo=timezone.utc)
                local_dt = utc_dt.astimezone(TIMEZONE)
                start_time = local_dt.strftime("%H:%M")
                slot_date  = local_dt.date()
            else:
                start_time = ""
                slot_date  = target_date
            duration_min = slot.get("duration")
            price        = parse_price(slot.get("price"))
            days_ahead   = (slot_date - snapshot_ts.date()).days

            rows.append({
                "datum_snapshot":  snapshot_ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "datum_slot":      slot_date.isoformat(),
                "uhrzeit_slot":    start_time,
                "dauer_minuten":   duration_min,
                "court":           court_name,
                "preis":           price,
                "status":          "frei",
                "tage_im_voraus":  days_ahead,
            })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    """Schreibt Zeilen in eine CSV-Datei."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "datum_snapshot", "datum_slot", "uhrzeit_slot",
        "dauer_minuten", "court", "preis", "status", "tage_im_voraus"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {len(rows)} Zeilen → {path}")


# ── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    snapshot_ts = datetime.now(tz=TIMEZONE)
    filename    = snapshot_ts.strftime("snapshot_%Y-%m-%d_%H%M.csv")
    output_path = OUTPUT_DIR / filename

    print(f"\nPadel Tracker — {snapshot_ts.strftime('%Y-%m-%d %H:%M')} Uhr")
    print(f"Scanne {DAYS_AHEAD + 1} Tage ({date.today()} bis "
          f"{date.today() + timedelta(days=DAYS_AHEAD)})\n")

    all_rows = []
    errors   = []

    for i in range(DAYS_AHEAD + 1):
        target_date = date.today() + timedelta(days=i)
        label = f"Tag +{i:02d}  {target_date}"
        try:
            api_data = fetch_slots(target_date)
            rows     = build_rows(snapshot_ts, target_date, api_data)
            all_rows.extend(rows)

            slot_count = sum(len(c.get("slots", [])) for c in api_data)
            print(f"  {label}  →  {slot_count} freie Slots "
                  f"({len(api_data)} Courts)")
        except Exception as e:
            print(f"  {label}  →  FEHLER: {e}")
            errors.append({"date": target_date.isoformat(), "error": str(e)})

    write_csv(all_rows, output_path)

    if errors:
        err_path = OUTPUT_DIR / f"errors_{snapshot_ts.strftime('%Y-%m-%d_%H%M')}.json"
        err_path.write_text(json.dumps(errors, indent=2))
        print(f"\n  ⚠ {len(errors)} Fehler → {err_path}")

    print(f"\nFertig. {len(all_rows)} Zeilen gesamt.\n")


if __name__ == "__main__":
    main()
