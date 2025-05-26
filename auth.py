from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

login_router = APIRouter()

users = {"test@example.com": {"password": "1234", "name": "홍길동"}}

class LoginRequest(BaseModel):
    email: str
    password: str

@login_router.post("/login")
def login(req: LoginRequest):
    user = users.get(req.email)
    if user and user["password"] == req.password:
        return {"success": True, "name": user["name"]}
    raise HTTPException(status_code=401, detail="Invalid credentials")
