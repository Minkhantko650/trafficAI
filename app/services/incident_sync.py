"""
Background job that fetches live TomTom incidents every 2 minutes
and syncs them into the incidents table automatically.
"""
import asyncio
import re
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from openai import AsyncOpenAI
from app.database import SessionLocal
from app.models import Incident
from app.config import settings

_translation_cache: dict = {}
_openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

def has_thai(text: str) -> bool:
    return any('\u0e00' <= c <= '\u0e7f' for c in text)

async def translate_to_english(text: str) -> str:
    if not text or not has_thai(text):
        return text
    if text in _translation_cache:
        return _translation_cache[text]
    try:
        resp = await _openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Translate this Bangkok road location from Thai to English. Return ONLY the translated location name, nothing else:\n{text}"
            }],
            max_tokens=80,
            temperature=0
        )
        result = resp.choices[0].message.content.strip()
        _translation_cache[text] = result
        return result
    except Exception:
        return text

def strip_thai(text: str) -> str:
    """Remove Thai characters, clean up leftover punctuation/spaces."""
    cleaned = re.sub(r'[\u0e00-\u0e7f]+', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' /,-.()[]')
    return cleaned

def english_location(from_loc: str, to_loc: str, road_numbers: list) -> str:
    """Build an English-only location string."""
    if road_numbers:
        return ", ".join(road_numbers)
    from_en = strip_thai(from_loc)
    to_en = strip_thai(to_loc)
    if from_en and to_en:
        return f"{from_en} to {to_en}"
    if from_en:
        return from_en
    if to_en:
        return to_en
    return "Bangkok Metropolitan Area"

def english_description(events: list) -> str:
    """Get English description, stripping any Thai that slipped through."""
    if not events:
        return "Traffic incident"
    raw = events[0].get("description", "Traffic incident")
    cleaned = strip_thai(raw)
    return cleaned if cleaned else "Traffic incident"

TOMTOM_BASE_URL = "https://api.tomtom.com"

# Bangkok bounding box — covers greater Bangkok area
BANGKOK_BBOX = {
    "min_lon": 100.35,
    "min_lat": 13.60,
    "max_lon": 100.75,
    "max_lat": 13.95
}

# TomTom iconCategory → our incident type
# Only real incidents — congestion (8, 14) handled by Flow API, not stored here
ICON_TO_TYPE = {
    1: "accident",
    2: "accident",
    3: "accident",
    4: "construction",
    5: "construction",
    6: "road_blockage",
    7: "road_blockage",
    9: "construction",
    10: "road_blockage",
    11: "weather_disruption",
}

SKIP_CATEGORIES = {8, 14}  # traffic jams — covered by /prediction/ blobs

# TomTom magnitudeOfDelay → our severity
MAGNITUDE_TO_SEVERITY = {
    0: "low",
    1: "low",
    2: "medium",
    3: "high",
    4: "critical"
}

async def fetch_tomtom_incidents() -> list:
    """Fetch all incidents in Bangkok from TomTom."""
    url = f"{TOMTOM_BASE_URL}/traffic/services/5/incidentDetails"
    bbox = BANGKOK_BBOX
    params = {
        "key": settings.TOMTOM_API_KEY,
        "bbox": f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}",
        "fields": "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers,timeValidity}}}",
        "language": "en-GB",
        "timeValidityFilter": "present"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=15)
        if response.status_code == 200:
            return response.json().get("incidents", [])
        return []

def normalize_incident(inc: dict) -> dict:
    """Convert raw TomTom incident into our Incident schema."""
    props = inc.get("properties", {})
    geometry = inc.get("geometry", {})
    coords = geometry.get("coordinates", [])

    # Get coordinates (first point of the incident)
    lat, lon = None, None
    if coords:
        first = coords[0] if isinstance(coords[0], list) else coords
        if len(first) >= 2:
            lon, lat = first[0], first[1]

    # Build description from events
    events = props.get("events", [])
    description = english_description(events)

    # Road numbers
    road_numbers = props.get("roadNumbers", [])
    affected_roads = ", ".join(road_numbers) if road_numbers else None

    # Store original location (may be Thai) — frontend handles language split
    from_loc = props.get("from", "")
    to_loc = props.get("to", "")
    location = f"{from_loc} to {to_loc}" if to_loc else from_loc
    if not location.strip():
        location = affected_roads or "Bangkok Metropolitan Area"

    # Type and severity — skip congestion categories
    icon_category = props.get("iconCategory", 0)
    if icon_category in SKIP_CATEGORIES:
        return None
    incident_type = ICON_TO_TYPE.get(icon_category, "accident")
    magnitude = props.get("magnitudeOfDelay", 0)
    severity = MAGNITUDE_TO_SEVERITY.get(magnitude, "low")

    # Delay
    delay = props.get("delay", 0)
    delay_min = round(delay / 60) if delay else 0
    estimated_clearance = f"~{delay_min} min delay" if delay_min > 0 else "Minor delay"

    return {
        "tomtom_id": props.get("id", ""),
        "type": incident_type,
        "description": description,
        "location": location[:255],
        "location_en": None,  # filled async after insert
        "affected_roads": affected_roads,
        "severity": severity,
        "status": "active",
        "estimated_clearance": estimated_clearance,
        "latitude": lat,
        "longitude": lon,
    }

async def sync_incidents_to_db(incidents: list):
    """Sync TomTom incidents into the database.

    - Deduplicates by tomtom_id (not location string) — no more duplicates
    - Resolves any active DB incidents whose tomtom_id is no longer in TomTom's response
    """
    db: Session = SessionLocal()
    new_count = 0
    updated_count = 0
    resolved_count = 0

    try:
        # Collect all valid tomtom_ids from this sync
        active_tomtom_ids = set()

        for inc in incidents:
            normalized = normalize_incident(inc)
            if normalized is None:
                continue
            tomtom_id = normalized.pop("tomtom_id")
            if not tomtom_id:
                continue

            active_tomtom_ids.add(tomtom_id)

            # Translate location before insert so location_en is always populated
            if has_thai(normalized["location"]):
                normalized["location_en"] = await translate_to_english(normalized["location"])
            else:
                normalized["location_en"] = normalized["location"]

            # Deduplicate by tomtom_id — the only reliable identity
            existing = db.query(Incident).filter(
                Incident.tomtom_id == tomtom_id
            ).first()

            if existing:
                # Update fields that can change between syncs
                existing.severity = normalized["severity"]
                existing.estimated_clearance = normalized["estimated_clearance"]
                existing.description = normalized["description"]
                existing.status = "active"  # reactivate if it was resolved
                if not existing.location_en:
                    existing.location_en = normalized["location_en"]
                existing.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                db_incident = Incident(tomtom_id=tomtom_id, **normalized)
                db.add(db_incident)
                new_count += 1

        # Resolve stale incidents — active in DB but no longer in TomTom's response
        # Only touch incidents that have a tomtom_id (synced ones), not manual entries
        if active_tomtom_ids:
            stale = db.query(Incident).filter(
                Incident.status == "active",
                Incident.tomtom_id.isnot(None),
                Incident.tomtom_id.notin_(list(active_tomtom_ids))
            ).all()
        else:
            stale = []

        for stale_inc in stale:
            stale_inc.status = "resolved"
            stale_inc.updated_at = datetime.utcnow()
            resolved_count += 1

        db.commit()
        print(
            f"[incident_sync] new={new_count} updated={updated_count} "
            f"resolved={resolved_count} | active_ids={len(active_tomtom_ids)}"
        )

    except Exception as e:
        print(f"[incident_sync] Error: {e}")
        db.rollback()
    finally:
        db.close()

async def run_incident_sync_loop():
    """Runs every 2 minutes to sync TomTom incidents."""
    print("[incident_sync] Background sync started.")
    while True:
        try:
            incidents = await fetch_tomtom_incidents()
            if incidents:
                await sync_incidents_to_db(incidents)
            else:
                print("[incident_sync] No incidents returned from TomTom.")
        except Exception as e:
            print(f"[incident_sync] Loop error: {e}")
        await asyncio.sleep(1800)  # wait 30 minutes
