from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Incident
from app.schemas import IncidentCreate, IncidentUpdate, IncidentOut
from app.services.traffic_service import strip_thai, has_thai
from typing import List, Optional

router = APIRouter(prefix="/incidents", tags=["Incidents"])

CONGESTION_TYPES = ["high_traffic_demand", "event_congestion"]
INCIDENT_TYPES   = ["accident", "construction", "road_blockage", "weather_disruption"]


def ensure_english_location(incident: Incident) -> Incident:
    """If location_en is missing, fall back to Thai-stripped location as best effort."""
    if not incident.location_en and has_thai(incident.location):
        stripped = strip_thai(incident.location)
        incident.location_en = stripped if stripped else incident.location
    elif not incident.location_en:
        incident.location_en = incident.location
    return incident


@router.get("/", response_model=List[IncidentOut])
def get_all(status: Optional[str] = None, kind: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    if kind == "congestion":
        query = query.filter(Incident.type.in_(CONGESTION_TYPES))
    elif kind == "incidents":
        query = query.filter(Incident.type.in_(INCIDENT_TYPES))
    incidents = query.order_by(Incident.created_at.desc()).limit(100).all()
    return [ensure_english_location(i) for i in incidents]

@router.get("/{incident_id}", response_model=IncidentOut)
def get_one(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident

@router.post("/", response_model=IncidentOut)
def create(incident: IncidentCreate, db: Session = Depends(get_db)):
    db_incident = Incident(**incident.model_dump())
    db.add(db_incident)
    db.commit()
    db.refresh(db_incident)
    return db_incident

@router.put("/{incident_id}", response_model=IncidentOut)
def update(incident_id: int, incident: IncidentUpdate, db: Session = Depends(get_db)):
    db_incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not db_incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    for key, value in incident.model_dump(exclude_unset=True).items():
        setattr(db_incident, key, value)
    db.commit()
    db.refresh(db_incident)
    return db_incident

@router.delete("/{incident_id}")
def delete(incident_id: int, db: Session = Depends(get_db)):
    db_incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not db_incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    db.delete(db_incident)
    db.commit()
    return {"message": "Deleted successfully"}
