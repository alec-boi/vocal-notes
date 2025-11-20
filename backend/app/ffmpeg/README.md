# DO NOT TOUCH THESE

    Ihese are mandatory binaries used by the yt_dlp Python library in format conversion and possibly download.
    Without them, upon trying to use a youtube link, the server will crash.

    It is also used by the voiceline separation API — thus why it is added to path at runtime.

    if you rather installing ffmpeg tools by yourself rather than running the provided binaries, you can do so 
    by installing the tool and configuring its PATH and removing the following lines

    ```
        BASE_DIR = Path(__file__).resolve().parent
        FFMPEG_BIN = BASE_DIR / "ffmpeg"

        os.environ["PATH"] = f"{FFMPEG_BIN}{os.pathsep}{os.environ['PATH']}"
    ```