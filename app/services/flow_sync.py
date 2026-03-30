"""
Background job that fetches live TomTom traffic flow for major Bangkok roads
every 5 minutes and saves snapshots + detects road closures automatically.
"""
import asyncio
import httpx
from typing import Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Incident
from app.config import settings

TOMTOM_BASE_URL = "https://api.tomtom.com"

# In-memory cache of latest flow readings — road name → flow data
# Filled by sync loop, read by query route for generic "is there traffic?" questions
ROAD_FLOW_CACHE: dict[str, dict] = {}

# In-memory geocoded coordinates — resolved once on startup via TomTom Search API
# road name → {"lat": float, "lon": float}
_ROAD_COORDS: dict[str, dict] = {}

# Just road names — TomTom Search API resolves coordinates at runtime.
# To add more roads, just append a name here — no lat/lon needed.
BANGKOK_ROAD_NAMES = [
    "Sukhumvit Road Bangkok",
    "Silom Road Bangkok",
    "Sathorn Road Bangkok",
    "Ratchadaphisek Road Bangkok",
    "Rama IV Road Bangkok",
    "Rama IX Road Bangkok",
    "Vibhavadi Rangsit Road Bangkok",
    "Lat Phrao Road Bangkok",
    "On Nut Road Bangkok",
    "Bang Na Expressway Bangkok",
    "Borommaratchachonnani Road Bangkok",
    "Phahonyothin Road Bangkok",
    "Petchaburi Road Bangkok",
    "Chaeng Watthana Road Bangkok",
    "Ngam Wong Wan Road Bangkok",
    "Ratchaphruek Road Bangkok",
    "Kanchanaphisek Road Bangkok",
    "Ramkhamhaeng Road Bangkok",
    "Srinakarin Road Bangkok",
    "Serithai Road Bangkok",
    "Rama II Road Bangkok",
    "Ekkamai Road Bangkok",
    "Thonglor Road Bangkok",
    "Asoke Road Bangkok",
    "Don Mueang Tollway Bangkok",
]


async def geocode_road_name(name: str) -> Optional[dict]:
    """Use TomTom Search API to resolve a road name to lat/lon."""
    url = f"{TOMTOM_BASE_URL}/search/2/search/{name}.json"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "limit": 1,
        "countrySet": "TH",
        "lat": 13.7563,
        "lon": 100.5018,
        "radius": 60000,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    pos = results[0].get("position", {})
                    return {"lat": pos["lat"], "lon": pos["lon"]}
    except Exception:
        pass
    return None


async def resolve_all_road_coords():
    """Geocode all road names on startup. Skips already resolved ones."""
    for name in BANGKOK_ROAD_NAMES:
        if name in _ROAD_COORDS:
            continue
        coords = await geocode_road_name(name)
        if coords:
            _ROAD_COORDS[name] = coords
            print(f"[flow_sync] Geocoded: {name} → ({coords['lat']:.4f}, {coords['lon']:.4f})")
        else:
            print(f"[flow_sync] Could not geocode: {name}")
        await asyncio.sleep(0.3)  # avoid hammering the search API

async def fetch_flow(lat: float, lon: float) -> dict:
    url = f"{TOMTOM_BASE_URL}/traffic/services/4/flowSegmentData/absolute/10/json"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "point": f"{lat},{lon}",
        "unit": "KMPH"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json().get("flowSegmentData", {})
        return {}

def get_congestion_level(current_speed: float, free_flow_speed: float) -> str:
    if free_flow_speed == 0:
        return "unknown"
    ratio = current_speed / free_flow_speed
    if ratio < 0.3:
        return "severely congested"
    elif ratio < 0.6:
        return "moderately congested"
    elif ratio < 0.8:
        return "slightly congested"
    else:
        return "flowing freely"

def handle_road_closure(db: Session, road_name: str, lat: float, lon: float):
    """Create or update a road closure incident when TomTom flags roadClosure=true."""
    existing = db.query(Incident).filter(
        Incident.location.contains(road_name),
        Incident.type == "road_blockage",
        Incident.status == "active"
    ).first()

    if not existing:
        closure = Incident(
            type="road_blockage",
            description=f"Road closure detected by live traffic sensor on {road_name}.",
            location=road_name,
            affected_roads=road_name,
            severity="critical",
            status="active",
            estimated_clearance="Unknown — monitor live updates",
            alternate_route="Check alternate routes via navigation app.",
            latitude=lat,
            longitude=lon
        )
        db.add(closure)
        db.commit()
        print(f"[flow_sync] Road closure detected and saved: {road_name}")

def resolve_cleared_closure(db: Session, road_name: str):
    """Resolve closure incident if TomTom no longer reports it as closed."""
    existing = db.query(Incident).filter(
        Incident.location.contains(road_name),
        Incident.type == "road_blockage",
        Incident.description.contains("live traffic sensor"),
        Incident.status == "active"
    ).first()

    if existing:
        existing.status = "resolved"
        db.commit()
        print(f"[flow_sync] Road closure resolved: {road_name}")

async def run_flow_sync_loop():
    """Geocodes all road names on first run, then syncs flow every 30 minutes."""
    print("[flow_sync] Traffic flow sync started — resolving road coordinates...")
    await resolve_all_road_coords()
    print(f"[flow_sync] Resolved {len(_ROAD_COORDS)}/{len(BANGKOK_ROAD_NAMES)} roads.")

    while True:
        db: Session = SessionLocal()
        try:
            for road_name, coords in _ROAD_COORDS.items():
                lat, lon = coords["lat"], coords["lon"]
                flow = await fetch_flow(lat, lon)
                if not flow:
                    continue

                road_closure = flow.get("roadClosure", False)
                current_speed = flow.get("currentSpeed", 0)
                free_flow_speed = flow.get("freeFlowSpeed", 0)
                congestion = get_congestion_level(current_speed, free_flow_speed)

                # Save to in-memory cache for generic chat queries
                ROAD_FLOW_CACHE[road_name] = {
                    "current_speed": current_speed,
                    "free_flow_speed": free_flow_speed,
                    "congestion": congestion,
                    "road_closure": road_closure,
                    "lat": lat,
                    "lon": lon,
                }

                if road_closure:
                    handle_road_closure(db, road_name, lat, lon)
                else:
                    resolve_cleared_closure(db, road_name)

                print(
                    f"[flow_sync] {road_name}: "
                    f"{current_speed} km/h (normal {free_flow_speed} km/h) — {congestion}"
                    + (" [CLOSED]" if road_closure else "")
                )

                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"[flow_sync] Error: {e}")
        finally:
            db.close()

        await asyncio.sleep(1800)  # 30 minutes


def format_all_roads_flow() -> str:
    """Format cached flow readings for all major roads into a GPT-readable summary."""
    if not ROAD_FLOW_CACHE:
        return "No cached road flow data available yet."

    lines = []
    for road_name, data in ROAD_FLOW_CACHE.items():
        if data["road_closure"]:
            status = "ROAD CLOSED"
        else:
            status = data["congestion"]
        lines.append(
            f"- {road_name}: {data['current_speed']} km/h "
            f"(normal {data['free_flow_speed']} km/h) — {status}"
        )

    return "\n".join(lines)


def find_road_by_query(query: str) -> tuple:
    """Match query string against known Bangkok roads using _ROAD_COORDS.
    Returns (road_name, {"lat": float, "lon": float}) or (None, None).
    """
    query_lower = query.lower()

    # Pass 1: match the road name minus the ' Bangkok' suffix
    for road_name in BANGKOK_ROAD_NAMES:
        key = road_name.lower().replace(" bangkok", "")
        if key in query_lower:
            coords = _ROAD_COORDS.get(road_name)
            if coords:
                return road_name, coords

    # Pass 2: match just the leading word (e.g. "sukhumvit", "silom")
    for road_name in BANGKOK_ROAD_NAMES:
        first_word = road_name.split()[0].lower()
        if len(first_word) > 4 and first_word in query_lower:
            coords = _ROAD_COORDS.get(road_name)
            if coords:
                return road_name, coords

    return None, None


def get_congested_roads() -> list:
    """Return roads that are not freely flowing, sorted worst-first."""
    order = {"ROAD CLOSED": 0, "severely congested": 1, "moderately congested": 2, "slightly congested": 3}
    result = []
    for road_name, data in ROAD_FLOW_CACHE.items():
        display = road_name.replace(" Bangkok", "")
        if data.get("road_closure"):
            result.append({"name": display, "congestion": "ROAD CLOSED", "current_speed": 0})
        elif data.get("congestion") in order:
            result.append({"name": display, "congestion": data["congestion"], "current_speed": data["current_speed"]})
    result.sort(key=lambda r: order.get(r["congestion"], 9))
    return result


def get_all_road_data() -> list:
    """Return all resolved road data for the /roads/ endpoint.
    Uses _ROAD_COORDS for positions and ROAD_FLOW_CACHE for live flow.
    Roads whose coordinates haven't been resolved yet are skipped.
    """
    result = []
    for road_name in BANGKOK_ROAD_NAMES:
        coords = _ROAD_COORDS.get(road_name)
        if not coords:
            continue
        flow = ROAD_FLOW_CACHE.get(road_name, {})
        display_name = road_name.replace(" Bangkok", "")
        result.append({
            "name": display_name,
            "lat": coords["lat"],
            "lng": coords["lon"],
            "current_speed": flow.get("current_speed", 0),
            "free_flow_speed": flow.get("free_flow_speed", 0),
            "congestion": flow.get("congestion", "unknown"),
            "road_closure": flow.get("road_closure", False),
        })
    return result
