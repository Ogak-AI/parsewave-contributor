from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from . import models, database

app = FastAPI()

@app.post("/users/")
def create_user(name: str, db: Session = Depends(database.get_db)):
    user = models.User(name=name)

    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user

@app.get("/users/")
def list_users(db: Session = Depends(database.get_db)):
    return db.query(models.User).all()
