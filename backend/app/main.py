import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from supabase import create_client
from pydantic import BaseModel
from audio_separator.separator import Separator
import yt_dlp
import uuid
import jwt
import requests
import asyncio

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE", "")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")

if not YOUTUBE_API_KEY:
    raise RuntimeError(
        "Set YOUTUBE_API_KEY in .env to enable YouTube functions")

BASE_DIR = Path(__file__).resolve().parent
FFMPEG_BIN = BASE_DIR / "ffmpeg"

os.environ["PATH"] = f"{FFMPEG_BIN}{os.pathsep}{os.environ['PATH']}"


class UrlPayload(BaseModel):
    url: str


supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

app = FastAPI(title="AudioAnalysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

progress_store = {}


async def generate_events(task_id):
    previous = None
    while True:
        progress = progress_store.get(task_id, None)

        if progress != previous:
            yield f"data: {progress}\n\n"
            previous = progress

        if progress == "done":
            break

        await asyncio.sleep(0.3)


@app.get("/dashboard")
def root():
    return {"ok": True, "msg": "API online"}


def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")

    token = authorization.split(" ")[1]

    try:
        user = supabase.auth.get_user(token)
        return user.user

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


security = HTTPBearer()


@app.post("/logout")
def logout():
    return {"message": "logged out"}


@app.post("/audio/process")
async def process_audio(payload: UrlPayload, user=Depends(verify_token)):
    task_id = str(uuid.uuid4())

    asyncio.create_task(
        process_audio_task(payload.url, user.id, task_id)
    )

    return {"task_id": task_id}


def process_audio_task(input_path, uid, task_id):
    progress_store[task_id] = "downloading"

    file_path = download_audio(input_path, uid)

    progress_store[task_id] = "separating"

    vocals = separate_voiceline(file_path, uid)

    progress_store[task_id] = "finalizing"
    return vocals


@app.get("/audio/progress/{task_id}")
async def progress_stream(task_id: str):
    return StreamingResponse(
        generate_events(task_id),
        media_type="text/event-stream"
    )


def download_audio(url: str, uid: str) -> str:
    audio_id = str(uuid.uuid4())
    out_dir = f"audio_downloads/{uid}"

    os.makedirs(out_dir, exist_ok=True)

    output_template = os.path.join(out_dir, f"{audio_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    downloaded_file = os.path.join(out_dir, f"{audio_id}.mp3")
    return downloaded_file


def separate_voiceline(input_path: str, uid: str):
    # I don't think these are required for production but my PC couldn't handle it so I had to add these
    # both these and the model chosen prioritize not destroying my PC in a detriment to performance so,
    # with an actual server it would probably be faster and consequently much better

    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["UVR_THREADS"] = "4"
    os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

    output_dir = Path("audio_vocals") / uid
    os.makedirs(output_dir, exist_ok=True)

    separator = Separator(output_dir=str(output_dir),
                          output_format="mp3", output_single_stem="vocals")
    model_name = "UVR-MDX-NET-Voc_FT.onnx"

    separator.load_model(model_name)

    result_paths = separator.separate(input_path)

    vocals_path = result_paths[0] if result_paths else None

    if vocals_path:
        original_path = Path(vocals_path)
        filename_uuid = original_path.name.split('_')[0]

        actual_file_path = None
        try:
            actual_file_path = next(output_dir.glob(f"{filename_uuid}*"))
        except StopIteration:
            print(
                f"Error: Could not find any output file starting with {filename_uuid} in {output_dir}")
            return None

        new_path = actual_file_path.parent / (filename_uuid + ".mp3")

        if new_path.exists():
            os.remove(new_path)

        try:
            os.rename(actual_file_path, new_path)
            vocals_path = str(new_path)
        except OSError as e:
            print(
                f"Error renaming file: {e}. Source: '{actual_file_path}' -> Destination: '{new_path}'")
            return None

    return vocals_path


# yes, I, in fact, did not program this by myself but I doubt a singular programmer that is not a Youtube technician or something like that
# will bother to learn their API nowadays, and just looking at this, I mean... Jesus H. Fucking Christ...


@app.get("/youtube/details", dependencies=[Depends(security)])
def get_video_details(
    video_id: str = Query(..., min_length=11, max_length=11),
):
    try:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,contentDetails",
            "id": video_id,
            "key": YOUTUBE_API_KEY,
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data.get('items'):
            item = data['items'][0]

            description = item['snippet'].get(
                'description', 'No description available.')

            channelTitle = item['snippet'].get(
                'channelTitle', 'No channel title available.')

            details = {
                "id": video_id,
                "title": item['snippet']['title'],
                "description": description,
                "channelTitle": channelTitle,
                "thumbnail": item['snippet']['thumbnails']['medium']['url'],
                "duration": item['contentDetails']['duration'],
            }

            return details

        raise HTTPException(status_code=404, detail="Video not found")

    except requests.exceptions.RequestException as e:
        print(f"YouTube API Error: {e}")
        raise HTTPException(
            status_code=500, detail="External API error (what the actual fuck happened to my poor yt this time?)")


@app.get("/youtube/search", dependencies=[Depends(security)])
def search_videos(
    query: str = Query(..., min_length=3),
    max_results: int = 3
):
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            if item['id']['kind'] == 'youtube#video':
                results.append({
                    "id": item['id']['videoId'],
                    "title": item['snippet']['title'],
                    "thumbnail": item['snippet']['thumbnails']['default']['url'],
                })

        return {"results": results}

    except requests.exceptions.RequestException as e:
        print(f"YouTube API Error: {e}")
        raise HTTPException(
            status_code=500, detail="External API error (not again...)")
