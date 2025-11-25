import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from supabase import create_client
from pydantic import BaseModel
from audio_separator.separator import Separator
from time import sleep
import yt_dlp
import uuid
import requests
import threading
import asyncio
import librosa
import numpy as np
import logging
from scipy.signal import medfilt

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("audio-api")

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

# Where processed vocal files will live (served under /files/)
AUDIO_OUTPUT_DIR = BASE_DIR / "audio_vocals"
AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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

# serve audio_vocals folder at /files
app.mount("/files", StaticFiles(directory=str(AUDIO_OUTPUT_DIR)), name="files")

progress_store = {}  # map task_id -> status string
results_store = {}    # map task_id -> result dict


async def generate_events(task_id):
    previous = None
    while True:
        progress = progress_store.get(task_id, None)

        if progress != previous:
            yield f"data: {progress}\n\n"
            previous = progress

        if progress == "done" or progress == "error":
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
def process_audio(payload: UrlPayload, user=Depends(verify_token)):
    task_id = str(uuid.uuid4())
    # initialize stores
    progress_store[task_id] = None
    results_store[task_id] = None

    thread = threading.Thread(
        target=process_audio_task, args=(
            payload.url, user.id, task_id), daemon=True
    )
    thread.start()
    logger.info(f"Started processing task {task_id} for user {user.id}")
    return {"task_id": task_id}


def process_audio_task(input_path, uid, task_id):
    try:
        progress_store[task_id] = "downloading"
        file_path = download_audio(input_path, uid)

        progress_store[task_id] = "separating"
        result = separate_voiceline(file_path, uid)

        progress_store[task_id] = "finalizing"
        # optional short wait for finalization
        sleep(1)

        # store result in results_store and mark done
        results_store[task_id] = result
        progress_store[task_id] = "done"
        logger.info(
            f"Task {task_id} finished: vocals_path={result.get('vocals_path')}, notes={len(result.get('notes', []))}")
        return result
    except Exception as e:
        # make sure client knows there was an error
        progress_store[task_id] = "error"
        results_store[task_id] = {"status": "error", "message": str(e)}
        logger.exception(f"process_audio_task error for task {task_id}: {e}")
        return None


@app.get("/audio/progress/{task_id}")
async def progress_stream(task_id: str):
    return StreamingResponse(
        generate_events(task_id),
        media_type="text/event-stream"
    )


@app.get("/audio/result/{task_id}")
def audio_result(task_id: str, user=Depends(verify_token)):
    """
    Return stored result for a finished task.
    MODIFIED: Now returns the raw, unfiltered notes directly from the detection function.
    """
    result = results_store.get(task_id)
    if not result:
        # if still in progress return 202
        status = progress_store.get(task_id)
        if status and status != "done":
            return JSONResponse(status_code=202, content={"status": "processing"})
        raise HTTPException(status_code=404, detail="Result not available")

    # result is the dict returned by separate_voiceline
    vocals_path = result.get("vocals_path")
    vocals_url = None
    if vocals_path:
        try:
            p = Path(vocals_path).resolve()
            if not p.exists():
                # helpful debug log for missing file
                logger.warning(
                    f"Requested vocals_path does not exist on disk: {p}")
                vocals_url = None
            else:
                rel = p.relative_to(AUDIO_OUTPUT_DIR.resolve())
                vocals_url = f"/files/{rel.as_posix()}"
        except Exception as exc:
            logger.exception(
                f"Error making vocals_url for task {task_id}: {exc}")
            vocals_url = None

    # notes are the raw frames returned by get_raw_note_frames
    notes = result.get("notes", []) or []

    # Ensure 'time' key is present for backward compatibility
    final_notes = []
    for note in notes:
        note["time"] = note["start"]
        final_notes.append(note)

    return {
        "status": result.get("status", "done"),
        "vocals_url": vocals_url,
        "notes": final_notes,
    }


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


def manual_hz_to_cents(f1, f2):
    """Calculate the musical difference in cents between two frequencies."""
    if f1 <= 0 or f2 <= 0:
        return np.nan  # Avoid division by zero or log of non-positive numbers
    return 1200 * np.log2(f2 / f1)


def separate_voiceline(input_path: str, uid: str):
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["UVR_THREADS"] = "4"
    os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

    output_dir = AUDIO_OUTPUT_DIR / uid
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
            # find the actual output file created by separator
            actual_file_path = next(output_dir.glob(f"{filename_uuid}*"))
        except StopIteration:
            logger.error(
                f"Could not find any output file starting with {filename_uuid} in {output_dir}")
            return {"status": "error", "vocals_path": None, "notes": []}

        new_path = actual_file_path.parent / (filename_uuid + ".mp3")

        if new_path.exists():
            try:
                os.remove(new_path)
            except Exception:
                logger.warning(f"Could not remove existing file {new_path}")

        try:
            os.rename(actual_file_path, new_path)
            vocals_path = str(new_path)
        except OSError as e:
            logger.exception(
                f"Error renaming file: {e}. Source: '{actual_file_path}' -> Destination: '{new_path}'")
            return {"status": "error", "vocals_path": None, "notes": []}
    else:
        return {"status": "error", "vocals_path": None, "notes": []}

    notes = get_segmented_vocal_notes(
        vocals_path, cents_tolerance=50) if vocals_path else []

    return {
        "status": "done",
        "vocals_path": vocals_path,
        "notes": notes
    }


def get_segmented_vocal_notes(audio_path, min_duration_sec=0.08, sr=44100, frame_length=1024, hop_length=128, cents_tolerance=25, silence_threshold_factor=0.35, merge_all_until_silence=True):
    """
    Analyzes an isolated vocal line to produce a list of segmented musical notes.
    Uses a SLOW adaptive envelope to detect silence relative to the current phrase volume.

    :param audio_path: Path to the audio file.
    :param merge_all_until_silence: If True, ignores pitch changes and only breaks notes on silence.
    :param silence_threshold_factor: Fraction of the local phrase volume to consider as silence (e.g. 0.2 = 20%).
    """
    if not audio_path:
        return []

    # 1. Load Audio and PYIN Analysis
    y, sr = librosa.load(audio_path, sr=sr, mono=True)

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=80, fmax=1100, sr=sr, frame_length=frame_length, hop_length=hop_length
    )

    # Smoothing the Pitch (Median Filter)
    f0_smoothed = medfilt(f0, kernel_size=5)
    frame_duration = hop_length / sr

    # --- ROBUST ADAPTIVE SILENCE DETECTION ---
    # Calculate RMS energy
    S = librosa.feature.rms(
        y=y, frame_length=frame_length, hop_length=hop_length)[0]

    # Calculate "Phrase Baseline" using a LARGE median filter window.
    # 1.5 seconds approx = 1.5 / frame_duration.
    # At 44.1k/128 hop, frame_duration is ~0.0029s. 1.5s is ~517 frames.
    # We ensure the kernel size is odd.
    long_window_size = int(1.5 / frame_duration)
    if long_window_size % 2 == 0:
        long_window_size += 1

    # This establishes the "context volume" (how loud the current phrase is generally)
    # It won't drop instantly when the singer breathes.
    PHRASE_BASELINE = medfilt(S, kernel_size=long_window_size)

    # Also calculate a global floor to prevent amplifying background noise during long silences
    global_noise_floor = np.percentile(S, 10)  # Bottom 10% is likely noise

    # ---------------------------------------------------------------
    # 2. Merging Logic 🤝
    # ---------------------------------------------------------------

    merged_notes = []
    current_segment = None
    segment_freqs = []

    for i, (freq_smoothed, voiced) in enumerate(zip(f0_smoothed, voiced_flag)):

        time_sec = i * frame_duration
        current_rms = S[i]

        # Dynamic Threshold: 20% (factor) of the recent phrase volume
        # But never go below the global noise floor (plus a small buffer)
        local_threshold = max(
            PHRASE_BASELINE[i] * silence_threshold_factor, global_noise_floor * 1.5)

        # Check: Is this frame LOUD?
        is_loud_enough = (current_rms >= local_threshold)

        # Check: Is this frame PITCHED?
        is_pitched = (voiced and not np.isnan(freq_smoothed))

        # We treat the frame as "Active Singing" if it is pitched AND loud enough.
        # If merge_all_until_silence is True, we mainly care about loudness continuity.
        if is_loud_enough and is_pitched:

            if current_segment is None:
                # Start new segment
                current_segment = {
                    "start": time_sec,
                    "end": time_sec + frame_duration,
                }
                segment_freqs = [freq_smoothed]
            else:
                # Check for pitch change (only if NOT merging all)
                note_has_changed = False

                if not merge_all_until_silence:
                    segment_avg_freq = np.mean(segment_freqs)
                    cents_diff = manual_hz_to_cents(
                        segment_avg_freq, freq_smoothed)
                    if abs(cents_diff) > cents_tolerance:
                        note_has_changed = True

                if not note_has_changed:
                    # Extend current note
                    current_segment['end'] = time_sec + frame_duration
                    segment_freqs.append(freq_smoothed)
                else:
                    # Break and start new note (Pitch changed)
                    final_note_freq = np.mean(segment_freqs)
                    merged_notes.append({
                        "start": current_segment['start'],
                        "end": current_segment['end'],
                        "freq": round(final_note_freq, 2),
                        "note": librosa.hz_to_note(final_note_freq)
                    })

                    current_segment = {
                        "start": time_sec,
                        "end": time_sec + frame_duration,
                    }
                    segment_freqs = [freq_smoothed]

        else:
            # --- POTENTIAL SILENCE / GAP ---

            if current_segment is not None:

                # If energy drops below the local threshold, it's a hard break (Silence)
                if current_rms < local_threshold:

                    final_note_freq = np.mean(segment_freqs)
                    merged_notes.append({
                        "start": current_segment['start'],
                        "end": time_sec,  # End at the start of silence
                        "freq": round(final_note_freq, 2),
                        "note": librosa.hz_to_note(final_note_freq)
                    })
                    current_segment = None
                    segment_freqs = []

                else:
                    # It's not pitched (e.g. consonant) but it's still loud (part of the phrase).
                    # Bridge the gap by extending the time, but don't add frequency (noise).
                    current_segment['end'] = time_sec + frame_duration

    # Finalize last note
    if current_segment is not None:
        final_note_freq = np.mean(segment_freqs)
        merged_notes.append({
            "start": current_segment['start'],
            "end": current_segment['end'],
            "freq": round(final_note_freq, 2),
            "note": librosa.hz_to_note(final_note_freq)
        })

    # 3. Filter Short Notes
    final_notes = []
    for note in merged_notes:
        duration = note['end'] - note['start']
        if duration >= min_duration_sec:
            final_notes.append({
                "start": round(note['start'], 3),
                "end": round(note['end'], 3),
                "duration": round(duration, 3),
                "note": note['note'],
                "freq": note['freq']
            })

    return final_notes


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
        logger.exception(f"YouTube API Error: {e}")
        raise HTTPException(status_code=500, detail="External API error")


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
        logger.exception(f"YouTube API Error: {e}")
        raise HTTPException(status_code=500, detail="External API error")
