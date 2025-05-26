from fastapi import FastAPI
from auth import login_router

app = FastAPI()

app.include_router(login_router)
