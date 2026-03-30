from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import FAQ
from app.schemas import FAQCreate, FAQUpdate, FAQOut
from typing import List

router = APIRouter(prefix="/faqs", tags=["FAQs"])

@router.get("/", response_model=List[FAQOut])
def get_all(db: Session = Depends(get_db)):
    return db.query(FAQ).all()

@router.get("/{faq_id}", response_model=FAQOut)
def get_one(faq_id: int, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return faq

@router.post("/", response_model=FAQOut)
def create(faq: FAQCreate, db: Session = Depends(get_db)):
    db_faq = FAQ(**faq.model_dump())
    db.add(db_faq)
    db.commit()
    db.refresh(db_faq)
    return db_faq

@router.put("/{faq_id}", response_model=FAQOut)
def update(faq_id: int, faq: FAQUpdate, db: Session = Depends(get_db)):
    db_faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not db_faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    for key, value in faq.model_dump(exclude_unset=True).items():
        setattr(db_faq, key, value)
    db.commit()
    db.refresh(db_faq)
    return db_faq

@router.delete("/{faq_id}")
def delete(faq_id: int, db: Session = Depends(get_db)):
    db_faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not db_faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    db.delete(db_faq)
    db.commit()
    return {"message": "Deleted successfully"}
