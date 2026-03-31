import httpx
import re
from app.config import settings


def strip_thai(text: str) -> str:
    """Remove Thai characters and clean up leftover punctuation/spaces."""
    if not text:
        return text
    cleaned = re.sub(r'[\u0e00-\u0e7f]+', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' /,-.()[]')
    return cleaned


def has_thai(text: str) -> bool:
    return any('\u0e00' <= c <= '\u0e7f' for c in (text or ''))

TOMTOM_BASE_URL = "https://api.tomtom.com"

# Named Bangkok locations — matched as whole phrases, used directly as geocode query
NAMED_LOCATIONS = [
    # Major roads
    "sukhumvit", "silom", "sathorn", "rama 1", "rama 2", "rama 3", "rama 4",
    "rama 9", "ratchada", "ratchadaphisek", "lat phrao", "ladprao", "phahonyothin",
    "vibhavadi", "vibhavadi rangsit", "bangna", "bangna trad", "petchburi",
    "phetchaburi", "ratchaphruek", "chaeng watthana", "ngam wong wan",
    "borommaratchachonnani", "pinklao", "asoke", "on nut", "udomsuk",
    "bearing", "ekkamai", "thonglor", "ari", "saphan khwai", "mo chit",
    "don mueang", "lad krabang", "srinakarin", "ramkhamhaeng",
    "serithai", "nakhon in", "kanchanaphisek", "outer ring road",
    "inner ring road", "expressway", "tollway", "highway",
    # Intersections / landmarks
    "asok", "asok intersection", "siam", "siam square", "pratunam",
    "victory monument", "chatuchak", "lumpini", "lumphini",
    "ratchaprasong", "rachaprasong", "bang sue", "bang rak",
    "bang kapi", "minburi", "lat krabang", "nonthaburi",
    "phra khanong", "on nut", "bearing", "samut prakan",
    "thonburi", "pinklao bridge", "rama 8 bridge", "saphan taksin",
    # BTS / MRT stations as location anchors
    "bts", "mrt", "hua lamphong", "silom station", "sala daeng",
    "chong nonsi", "surasak", "saphan taksin", "krung thon buri",
    "wongwian yai", "bearing station", "on nut station",
    # Sois
    "soi", "soi sukhumvit",
    # Generic road words (used as fallback)
    "road", "street", "avenue", "rd", "st", "thanon",
]

async def geocode_road(query: str) -> tuple:
    """Extract location name from query and geocode it to lat/lon using TomTom."""
    query_lower = query.lower()
    matched_location = None

    # Sort by length descending so longer/more specific phrases match first
    for keyword in sorted(NAMED_LOCATIONS, key=len, reverse=True):
        if keyword in query_lower:
            matched_location = keyword
            break

    if not matched_location:
        return None, None

    # Use TomTom fuzzy search (more forgiving than geocode endpoint)
    search_query = f"{matched_location} Bangkok Thailand"
    url = f"{TOMTOM_BASE_URL}/search/2/search/{search_query}.json"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "limit": 1,
        "countrySet": "TH",
        "lat": 13.7563,
        "lon": 100.5018,
        "radius": 50000,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                pos = results[0].get("position", {})
                return pos.get("lat"), pos.get("lon")

    return None, None

# TomTom magnitudeOfDelay values
DELAY_SEVERITY = {
    0: "unknown severity",
    1: "minor delay",
    2: "moderate delay",
    3: "major delay",
    4: "undefined delay"
}

async def get_traffic_incidents(lat: float, lon: float, radius: int = 5000, wide: bool = False):
    url = f"{TOMTOM_BASE_URL}/traffic/services/5/incidentDetails"
    # wide=True covers all of Bangkok metro (~30km radius) for general queries
    delta = 0.27 if wide else 0.05
    params = {
        "key": settings.TOMTOM_API_KEY,
        "bbox": f"{lon-delta},{lat-delta},{lon+delta},{lat+delta}",
        "fields": "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers,timeValidity}}}",
        "language": "en-GB",
        "timeValidityFilter": "present"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=8)
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return {"incidents": []}

async def get_traffic_flow(lat: float, lon: float):
    url = f"{TOMTOM_BASE_URL}/traffic/services/4/flowSegmentData/absolute/10/json"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "point": f"{lat},{lon}",
        "unit": "KMPH"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=8)
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return {}

def get_first_incident_coords(incidents_data: dict) -> tuple:
    """Return lat/lon of the most severe live incident from TomTom response."""
    incidents = incidents_data.get("incidents", [])
    if not incidents:
        return None, None

    # Sort by magnitudeOfDelay descending to get worst first
    sorted_incs = sorted(
        incidents,
        key=lambda i: i.get("properties", {}).get("magnitudeOfDelay", 0),
        reverse=True
    )

    for inc in sorted_incs:
        geometry = inc.get("geometry", {})
        geo_type = geometry.get("type", "")
        coords = geometry.get("coordinates", [])
        if not coords:
            continue

        try:
            if geo_type == "Point":
                # coords = [lon, lat]
                return coords[1], coords[0]
            else:
                # LineString/MultiLineString: coords = [[lon, lat], ...]
                # Use midpoint of the line for better accuracy
                first = coords[0] if isinstance(coords[0], list) else coords
                if len(first) >= 2:
                    return first[1], first[0]
        except (IndexError, TypeError):
            continue

    return None, None


ICON_CATEGORY_LABEL = {
    0: "Incident",
    1: "Accident",
    2: "Fog",
    3: "Dangerous Conditions",
    4: "Rain",
    5: "Ice",
    6: "Traffic Jam",
    7: "Lane Closed",
    8: "Road Closed",
    9: "Road Works",
    10: "High Winds",
    11: "Flooding",
    14: "Broken Down Vehicle",
}

def _is_useful_location(text: str) -> bool:
    """Return False if text is empty, purely numeric, a short code, or a highway number pattern."""
    if not text or not text.strip():
        return False
    cleaned = text.strip()
    # Purely numeric (e.g. "307", "6") or very short (e.g. "A", "B1")
    if re.match(r'^[\d\s\-/]+$', cleaned):
        return False
    if len(cleaned) <= 2:
        return False
    # Highway/route number patterns: "Road 31", "Route 9", "Highway 1", "AH1", "TH-31"
    if re.match(r'^(?:road|route|highway|hwy|rd|no\.?|th[-\s]?|ah)\s*\d+$', cleaned, re.IGNORECASE):
        return False
    # Just a number with a suffix like "31N", "2A"
    if re.match(r'^\d+[a-z]?$', cleaned, re.IGNORECASE):
        return False
    return True

def format_incidents_for_context(incidents_data: dict) -> str:
    incidents = incidents_data.get("incidents", [])
    if not incidents:
        return "No active traffic incidents reported in this area."

    # Sort by magnitudeOfDelay descending (most severe first)
    incidents = sorted(
        incidents,
        key=lambda i: i.get("properties", {}).get("magnitudeOfDelay", 0),
        reverse=True
    )

    lines = []
    for inc in incidents[:5]:
        props = inc.get("properties", {})
        events = props.get("events", [{}])
        delay = props.get("delay", 0)
        magnitude = props.get("magnitudeOfDelay", 0)
        icon_cat = props.get("iconCategory", 0)
        if events:
            icon_cat = events[0].get("iconCategory", icon_cat)

        incident_type = ICON_CATEGORY_LABEL.get(icon_cat, "Incident")
        severity_text = DELAY_SEVERITY.get(magnitude, "unknown severity")
        delay_min = round(delay / 60) if delay else 0
        delay_text = f"{delay_min} min delay" if delay_min > 0 else "no significant delay"

        # Try to get a human-readable location
        raw_from = props.get("from", "")
        raw_to   = props.get("to", "")
        clean_from = strip_thai(raw_from).strip() if raw_from else ""
        clean_to   = strip_thai(raw_to).strip()   if raw_to   else ""

        # Prefer cleaned text; fall back to original if Thai stripping left something readable
        from_loc = clean_from if _is_useful_location(clean_from) else (raw_from if _is_useful_location(raw_from) else "")
        to_loc   = clean_to   if _is_useful_location(clean_to)   else (raw_to   if _is_useful_location(raw_to)   else "")

        # Build location string — only include from/to if they look like real place names
        if from_loc and to_loc:
            location_text = f" between {from_loc} and {to_loc}"
        elif from_loc:
            location_text = f" near {from_loc}"
        else:
            location_text = ""

        lines.append(
            f"- {incident_type}{location_text}. "
            f"Severity: {severity_text}. Delay: {delay_text}."
        )

    return "\n".join(lines) if lines else "No active traffic incidents reported in this area."

async def geocode_place(name: str) -> tuple:
    """Geocode any place name in Bangkok context using TomTom Search."""
    params_base = {
        "key": settings.TOMTOM_API_KEY,
        "limit": 1,
        "countrySet": "TH",
        "lat": 13.7563,
        "lon": 100.5018,
        "radius": 50000,
    }
    queries = [
        f"{name} Bangkok",
        f"{name} Bangkok Thailand",
        name,
    ]
    try:
        async with httpx.AsyncClient() as client:
            for query in queries:
                url = f"{TOMTOM_BASE_URL}/search/2/search/{query}.json"
                r = await client.get(url, params=params_base, timeout=10)
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    if results:
                        pos = results[0]["position"]
                        print(f"[geocode] '{name}' → '{query}' → ({pos['lat']}, {pos['lon']})")
                        return pos["lat"], pos["lon"]
    except Exception as e:
        print(f"[geocode] Error for '{name}': {e}")
    # Fallback: try TomTom POI search (better for malls, landmarks, named places)
    try:
        async with httpx.AsyncClient() as client:
            poi_url = f"{TOMTOM_BASE_URL}/search/2/poiSearch/{name}.json"
            poi_params = {
                "key": settings.TOMTOM_API_KEY,
                "limit": 1,
                "countrySet": "TH",
                "lat": 13.7563,
                "lon": 100.5018,
                "radius": 50000,
            }
            r = await client.get(poi_url, params=poi_params, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    pos = results[0]["position"]
                    print(f"[geocode] POI match for '{name}' → ({pos['lat']}, {pos['lon']})")
                    return pos["lat"], pos["lon"]
    except Exception as e:
        print(f"[geocode] POI search error for '{name}': {e}")

    print(f"[geocode] Could not geocode '{name}'")
    return None, None


async def calculate_route_arrive_at(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
    arrive_at_iso: str,
) -> dict | None:
    """Call TomTom Routing with arriveAt to get recommended departure time.
    arrive_at_iso: 'YYYY-MM-DDTHH:mm:ss' Bangkok local time.
    Returns {depart_time_str, arrive_time_str, travel_time_mins, length_km} or None.
    """
    url = (
        f"{TOMTOM_BASE_URL}/routing/1/calculateRoute"
        f"/{from_lat},{from_lon}:{to_lat},{to_lon}/json"
    )
    params = {
        "key": settings.TOMTOM_API_KEY,
        "arriveAt": arrive_at_iso,
        "travelMode": "car",
        "routeType": "fastest",
        "traffic": "true",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"[arriveAt] TomTom error {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            route = data["routes"][0]
            s = route["summary"]
            depart_raw = s.get("departureTime", "")
            arrive_raw = s.get("arrivalTime", "")

            def fmt(iso: str) -> str:
                # "2025-03-31T17:10:00+07:00" → "5:10 PM"
                try:
                    t = iso[11:16]  # "HH:MM"
                    h, m = int(t[:2]), int(t[3:])
                    meridiem = "AM" if h < 12 else "PM"
                    h12 = h % 12 or 12
                    return f"{h12}:{m:02d} {meridiem}"
                except Exception:
                    return iso

            points = [
                [p["latitude"], p["longitude"]]
                for p in route["legs"][0]["points"]
            ]
            return {
                "depart_time_str": fmt(depart_raw),
                "arrive_time_str": fmt(arrive_raw),
                "travel_time_mins": round(s["travelTimeInSeconds"] / 60),
                "length_km": round(s["lengthInMeters"] / 1000, 1),
                "route_points": points,
            }
    except Exception as e:
        print(f"[arriveAt] Error: {e}")
        return None


async def calculate_route(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
    avoid_lat: float = None, avoid_lon: float = None,
) -> tuple:
    """Call TomTom Routing API. Returns (route_points, summary) or (None, None).
    route_points = [[lat, lng], ...]
    summary = {travel_time_mins, length_km, traffic_delay_mins}
    """
    url = (
        f"{TOMTOM_BASE_URL}/routing/1/calculateRoute"
        f"/{from_lat},{from_lon}:{to_lat},{to_lon}/json"
    )
    params = {
        "key": settings.TOMTOM_API_KEY,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
    }
    try:
        async with httpx.AsyncClient() as client:
            if avoid_lat is not None and avoid_lon is not None:
                r = 0.012  # ~1.3 km box around the congested road point
                body = {
                    "avoidAreas": {
                        "rectangles": [{
                            "southWestCorner": {
                                "latitude": round(avoid_lat - r, 6),
                                "longitude": round(avoid_lon - r, 6),
                            },
                            "northEastCorner": {
                                "latitude": round(avoid_lat + r, 6),
                                "longitude": round(avoid_lon + r, 6),
                            },
                        }]
                    }
                }
                resp = await client.post(url, params=params, json=body, timeout=15)
            else:
                resp = await client.get(url, params=params, timeout=15)

            if resp.status_code != 200:
                return None, None

            data = resp.json()
            route = data["routes"][0]
            points = [
                [p["latitude"], p["longitude"]]
                for p in route["legs"][0]["points"]
            ]
            s = route["summary"]
            summary = {
                "travel_time_mins": round(s["travelTimeInSeconds"] / 60),
                "length_km": round(s["lengthInMeters"] / 1000, 1),
                "traffic_delay_mins": round(s.get("trafficDelayInSeconds", 0) / 60),
            }
            return points, summary
    except Exception:
        return None, None


def format_flow_for_context(flow_data: dict) -> str:
    flow = flow_data.get("flowSegmentData", {})
    if not flow:
        return "No traffic flow data available."

    current_speed = flow.get("currentSpeed", 0)
    free_flow_speed = flow.get("freeFlowSpeed", 0)
    current_travel_time = flow.get("currentTravelTime", 0)
    free_flow_travel_time = flow.get("freeFlowTravelTime", 0)
    road_closure = flow.get("roadClosure", False)

    if road_closure:
        return "ROAD CLOSED at this location according to live data."

    if free_flow_speed > 0:
        ratio = current_speed / free_flow_speed
        if ratio < 0.3:
            congestion = "severely congested"
        elif ratio < 0.6:
            congestion = "moderately congested"
        elif ratio < 0.8:
            congestion = "slightly congested"
        else:
            congestion = "flowing freely"
    else:
        congestion = "unknown"

    delay_seconds = current_travel_time - free_flow_travel_time
    delay_min = round(delay_seconds / 60) if delay_seconds > 0 else 0
    delay_text = f" Adding ~{delay_min} min to normal travel time." if delay_min > 0 else " No added delay."

    return (
        f"Current speed: {current_speed} km/h (normal: {free_flow_speed} km/h). "
        f"Traffic is {congestion}.{delay_text}"
    )
