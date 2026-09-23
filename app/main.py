from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .database import engine, Base, SessionLocal
from . import models

app = FastAPI(title="AutoDeskAI Backend")

# Create database tables
Base.metadata.create_all(bind=engine)


# Request model for updating a user
class UserUpdate(BaseModel):
    name: str
    email: str


# Database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def root():
    return {
        "message": "AutoDeskAI Backend is running"
    }


@app.get("/db-test")
def database_test():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))

            return {
                "status": "success",
                "database": "PostgreSQL connected",
                "result": result.scalar()
            }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(models.User).all()

    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email
        }
        for user in users
    ]


@app.post("/users")
def create_user(
    name: str,
    email: str,
    db: Session = Depends(get_db)
):
    new_user = models.User(
        name=name,
        email=email
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "name": new_user.name,
        "email": new_user.email
    }


@app.put("/users/{user_id}")
def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    user.name = user_data.name
    user.email = user_data.email

    db.commit()
    db.refresh(user)

    return {
        "status": "success",
        "message": "User updated successfully",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email
        }
    }


@app.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    db.delete(user)
    db.commit()

    return {
        "status": "success",
        "message": f"User {user_id} deleted successfully"
    }