from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import KnowledgeEntry
from app.schemas import KnowledgeEntryCreate, KnowledgeEntryUpdate, KnowledgeEntryOut
from typing import List

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])

@router.get("/", response_model=List[KnowledgeEntryOut])
def get_all(db: Session = Depends(get_db)):
    return db.query(KnowledgeEntry).all()

@router.get("/{entry_id}", response_model=KnowledgeEntryOut)
def get_one(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry

@router.post("/", response_model=KnowledgeEntryOut)
def create(entry: KnowledgeEntryCreate, db: Session = Depends(get_db)):
    db_entry = KnowledgeEntry(**entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry

@router.put("/{entry_id}", response_model=KnowledgeEntryOut)
def update(entry_id: int, entry: KnowledgeEntryUpdate, db: Session = Depends(get_db)):
    db_entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for key, value in entry.model_dump(exclude_unset=True).items():
        setattr(db_entry, key, value)
    db.commit()
    db.refresh(db_entry)
    return db_entry

@router.delete("/{entry_id}")
def delete(entry_id: int, db: Session = Depends(get_db)):
    db_entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(db_entry)
    db.commit()
    return {"message": "Deleted successfully"}
