import asyncio
from fastapi import APIRouter, Query
from app.services.flow_sync import fetch_flow

router = APIRouter(prefix="/prediction", tags=["Prediction"])

# Expanded Bangkok road coverage — 25 points across the city
BANGKOK_COVERAGE = [
    # Central
    {"name": "Sukhumvit Road",         "lat": 13.7440, "lng": 100.5601},
    {"name": "Silom Road",             "lat": 13.7248, "lng": 100.5289},
    {"name": "Sathorn Road",           "lat": 13.7220, "lng": 100.5250},
    {"name": "Rama IV Road",           "lat": 13.7280, "lng": 100.5350},
    {"name": "Ratchadamri Road",       "lat": 13.7450, "lng": 100.5400},
    # North
    {"name": "Vibhavadi Rangsit Road", "lat": 13.8200, "lng": 100.5550},
    {"name": "Phahonyothin Road",      "lat": 13.8320, "lng": 100.5750},
    {"name": "Ratchadaphisek Road",    "lat": 13.7700, "lng": 100.5695},
    {"name": "Lat Phrao Road",         "lat": 13.8000, "lng": 100.5700},
    {"name": "Ram Inthra Road",        "lat": 13.8650, "lng": 100.6200},
    {"name": "Chaeng Watthana Road",   "lat": 13.8850, "lng": 100.5350},
    # East
    {"name": "On Nut Road",            "lat": 13.7012, "lng": 100.5998},
    {"name": "Srinakarin Road",        "lat": 13.6850, "lng": 100.6350},
    {"name": "Bearing Road",           "lat": 13.6620, "lng": 100.6100},
    {"name": "Rama IX Road",           "lat": 13.7230, "lng": 100.6050},
    {"name": "Ekkamai Road",           "lat": 13.7200, "lng": 100.5850},
    # South / Bang Na
    {"name": "Bang Na Expressway",     "lat": 13.6800, "lng": 100.6050},
    {"name": "Sukhumvit Soi 103",      "lat": 13.6700, "lng": 100.6200},
    {"name": "Pracha Uthit Road",      "lat": 13.6950, "lng": 100.5650},
    # West / Thonburi
    {"name": "Borommaratchachonnani",  "lat": 13.7830, "lng": 100.4530},
    {"name": "Phetkasem Road",         "lat": 13.7200, "lng": 100.4650},
    {"name": "Ratchaphruek Road",      "lat": 13.7900, "lng": 100.4200},
    # Inner city
    {"name": "Yaowarat Road",          "lat": 13.7400, "lng": 100.5100},
    {"name": "Charoen Krung Road",     "lat": 13.7180, "lng": 100.5130},
    {"name": "Asok-Din Daeng Road",    "lat": 13.7580, "lng": 100.5680},
]

def get_level(current: float, free_flow: float, closed: bool) -> str:
    if closed:
        return "critical"
    if free_flow == 0:
        return "unknown"
    ratio = current / free_flow
    if ratio < 0.3:
        return "critical"
    elif ratio < 0.6:
        return "high"
    elif ratio < 0.8:
        return "moderate"
    else:
        return "low"

@router.get("/")
async def get_prediction():
    tasks = [fetch_flow(r["lat"], r["lng"]) for r in BANGKOK_COVERAGE]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    zones = []
    for road, flow in zip(BANGKOK_COVERAGE, results):
        if isinstance(flow, Exception) or not flow:
            continue
        current = flow.get("currentSpeed", 0)
        free_flow = flow.get("freeFlowSpeed", 0)
        closed = flow.get("roadClosure", False)
        level = get_level(current, free_flow, closed)
        if level == "unknown":
            continue
        zones.append({
            "name": road["name"],
            "lat": road["lat"],
            "lng": road["lng"],
            "level": level,
            "current_speed": current,
            "free_flow_speed": free_flow,
            "road_closure": closed,
        })

    return {"zones": zones}


@router.get("/area")
async def get_area_prediction(
    lat1: float = Query(...), lng1: float = Query(...),
    lat2: float = Query(...), lng2: float = Query(...),
    zoom: int = Query(12),
):
    """
    Dynamically fetch flow data for a grid of points within the given bounding box.
    Grid density increases with zoom level so users see more detail when zoomed in.
    """
    # Step in degrees — finer at higher zoom
    STEP = {10: 0.05, 11: 0.03, 12: 0.02, 13: 0.012, 14: 0.007, 15: 0.004, 16: 0.003}
    step = STEP.get(zoom, 0.02 if zoom < 14 else 0.003)

    min_lat, max_lat = min(lat1, lat2), max(lat1, lat2)
    min_lng, max_lng = min(lng1, lng2), max(lng1, lng2)

    points = []
    lat = min_lat
    while lat <= max_lat:
        lng = min_lng
        while lng <= max_lng:
            points.append((round(lat, 5), round(lng, 5)))
            lng += step
        lat += step
        if len(points) >= 40:
            break

    points = points[:40]

    tasks = [fetch_flow(p[0], p[1]) for p in points]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    zones = []
    seen: set = set()
    for (plat, plng), flow in zip(points, results):
        if isinstance(flow, Exception) or not flow:
            continue
        current = flow.get("currentSpeed", 0)
        free_flow = flow.get("freeFlowSpeed", 0)
        closed = flow.get("roadClosure", False)
        level = get_level(current, free_flow, closed)
        if level == "unknown":
            continue
        # Deduplicate points that TomTom snaps to the same road segment
        key = f"{round(plat * 200)},{round(plng * 200)}"
        if key in seen:
            continue
        seen.add(key)
        zones.append({
            "name": f"{plat:.3f},{plng:.3f}",
            "lat": plat,
            "lng": plng,
            "level": level,
            "current_speed": current,
            "free_flow_speed": free_flow,
            "road_closure": closed,
        })

    return {"zones": zones}
