import os
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client
import jwt
import requests

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

app = FastAPI(title="AudioAnalysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/dashboard")
def root():
    return {"ok": True, "msg": "API online"}


def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(
            status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SUPABASE_ANON_KEY, algorithms=[
                             "HS256"], options={"verify_aud": False})
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


security = HTTPBearer()


@app.get("/protected")
def protected_route(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    res = requests.get(
        "https://tbdybvrpmymynsryjxfk.supabase.co/auth/v1/user",
        headers={"Authorization": f"Bearer {token}"}
    )
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"message": "Hello from FastAPI, authenticated user!"}


@app.post("/logout")
def logout():
    return {"message": "logged out"}
