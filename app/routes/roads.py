from fastapi import APIRouter
from app.services.flow_sync import get_all_road_data

router = APIRouter(prefix="/roads", tags=["Roads"])


@router.get("/")
def get_roads():
    """Return all 25 Bangkok roads with their TomTom-geocoded coordinates
    and latest live flow data from the flow_sync cache.
    """
    return {"roads": get_all_road_data()}
