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

async def get_traffic_incidents(lat: float, lon: float, radius: int = 5000):
    url = f"{TOMTOM_BASE_URL}/traffic/services/5/incidentDetails"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "bbox": f"{lon-0.05},{lat-0.05},{lon+0.05},{lat+0.05}",
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


def format_incidents_for_context(incidents_data: dict) -> str:
    incidents = incidents_data.get("incidents", [])
    if not incidents:
        return "No active traffic incidents reported in this area."

    lines = []
    for inc in incidents[:5]:
        props = inc.get("properties", {})
        events = props.get("events", [{}])
        raw_desc = events[0].get("description", "Unknown incident") if events else "Unknown incident"
        description = strip_thai(raw_desc) or raw_desc
        from_loc = strip_thai(props.get("from", "Unknown location")) or props.get("from", "Unknown location")
        to_loc = strip_thai(props.get("to", ""))
        road_numbers = props.get("roadNumbers", [])
        delay = props.get("delay", 0)
        magnitude = props.get("magnitudeOfDelay", 0)

        # Specific delay time
        delay_min = round(delay / 60) if delay else 0
        delay_text = f"{delay_min} min delay" if delay_min > 0 else "no significant delay"

        # Severity from magnitudeOfDelay
        severity_text = DELAY_SEVERITY.get(magnitude, "unknown severity")

        # Road name
        road_text = f" on {', '.join(road_numbers)}" if road_numbers else ""
        route_text = f" from {from_loc} to {to_loc}" if to_loc else f" near {from_loc}"

        lines.append(
            f"- {description}{road_text}{route_text}. "
            f"Severity: {severity_text}. Delay: {delay_text}."
        )

    return "\n".join(lines)

async def geocode_place(name: str) -> tuple:
    """Geocode any place name in Bangkok context using TomTom Search."""
    query = f"{name} Bangkok Thailand"
    url = f"{TOMTOM_BASE_URL}/search/2/search/{query}.json"
    params = {
        "key": settings.TOMTOM_API_KEY,
        "limit": 1,
        "countrySet": "TH",
        "lat": 13.7563,
        "lon": 100.5018,
        "radius": 50000,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    pos = results[0]["position"]
                    return pos["lat"], pos["lon"]
    except Exception:
        pass
    return None, None


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
