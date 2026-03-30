from fastapi import APIRouter, Query, Depends
import httpx
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import TravelTimeLog

router = APIRouter(prefix="/route", tags=["Route"])

@router.get("/")
async def calculate_route(
    from_lat: float = Query(...),
    from_lon: float = Query(...),
    to_lat: float = Query(...),
    to_lon: float = Query(...),
    dest_name: str = Query(default=""),
    db: Session = Depends(get_db),
):
    url = (
        f"https://api.tomtom.com/routing/1/calculateRoute"
        f"/{from_lat},{from_lon}:{to_lat},{to_lon}/json"
    )
    params = {
        "key": settings.TOMTOM_API_KEY,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=15)
        if response.status_code != 200:
            return {"error": "Could not calculate route", "points": [], "summary": {}}
        data = response.json()

    route = data["routes"][0]
    points = [
        [p["latitude"], p["longitude"]]
        for p in route["legs"][0]["points"]
    ]
    summary = route["summary"]

    travel_time_mins = round(summary["travelTimeInSeconds"] / 60)

    # Log for historical predictions
    if dest_name:
        now = datetime.now(timezone.utc)
        log = TravelTimeLog(
            dest_name=dest_name.lower().strip(),
            dest_lat=to_lat,
            dest_lng=to_lon,
            day_of_week=now.weekday(),
            hour=now.hour,
            travel_time_mins=travel_time_mins,
        )
        db.add(log)
        db.commit()

    return {
        "points": points,
        "summary": {
            "travel_time_mins": travel_time_mins,
            "length_km": round(summary["lengthInMeters"] / 1000, 1),
            "traffic_delay_mins": round(summary.get("trafficDelayInSeconds", 0) / 60),
        }
    }
