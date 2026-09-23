# Derived from browser-use/video-use helpers/transcribe.py (MIT, Copyright (c) 2026 Browser Use).
# See THIRD_PARTY_NOTICES.md.
"""Transcribe a take to word-level JSON, with ElevenLabs Scribe or locally.

Writes <edit_dir>/transcripts/<video_stem>.json. That file is also the cache:
if it exists, nothing is uploaded and nothing is paid for. It is keyed on the
file NAME only, so after replacing a take, delete the old transcript by hand.

Backends:
  scribe   ElevenLabs Scribe (paid): mono 16 kHz audio is uploaded with
           diarisation, audio-event tags and word-level timestamps.
  local    faster-whisper or openai-whisper on this machine (transcribe_local.py).
  auto     scribe when a key exists, local otherwise (the default).

Normally run through `lc intake`. Directly, from the project:

    lc transcribe ../take1.mov --edit-dir . [--backend auto|scribe|local]
                  [--language ar] [--num-speakers 2] [--model large-v3]

(lc runs every tool from inside edit/, so the take is ../take1.mov.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def load_api_key(required: bool = True) -> str:
    """The Scribe key: the ELEVENLABS_API_KEY environment variable, then
    $LESSON_CUT_HOME/env (default ~/.lesson-cut/env). Nowhere else.

    Never from inside the plugin or the project: a key there is one `git add`
    away from being published, and this plugin gets shared. An empty value is
    skipped rather than treated as the answer. lc doctor checks the same two
    places, so the two can never disagree about whether a key exists.
    """
    v = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if v:
        return v
    lc_home = Path(os.environ.get("LESSON_CUT_HOME") or (Path.home() / ".lesson-cut"))
    env_file = lc_home / "env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            if k.strip() == "ELEVENLABS_API_KEY" and val:
                return val
    if required:
        # umask 077: the file holds a secret, and the default umask makes it
        # world-readable. Full paths, because lc is on nobody's PATH. The local
        # route installs the recogniser first: a fresh setup has none, and
        # `intake --backend local` alone would only fail again.
        root = Path(__file__).resolve().parent.parent
        lc = root / "scripts" / "lc"
        sys.exit("no ELEVENLABS_API_KEY.\n"
                 f"  set one:  (umask 077; mkdir -p \"{lc_home}\" && echo 'ELEVENLABS_API_KEY=sk_...' > \"{env_file}\")\n"
                 "  or run locally with no key:\n"
                 f"      bash \"{root}/scripts/setup.sh\" --local-asr\n"
                 f"      \"{lc}\" intake --backend local")
    return ""


def extract_audio(video_path: Path, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call_scribe(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
) -> dict:
    data: dict[str, str] = {
        "model_id": "scribe_v1",
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language
    if num_speakers:
        data["num_speakers"] = str(num_speakers)

    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                SCRIBE_URL,
                headers={"xi-api-key": api_key},
                files={"file": (audio_path.name, f, "audio/wav")},
                data=data,
                timeout=1800,
            )
    except requests.RequestException as e:
        # One line, not four chained tracebacks: the network is the usual cause.
        sys.exit(f"Scribe request failed: {type(e).__name__}: {e}\n"
                 "Nothing was cached; re-run lc intake to retry.")

    if resp.status_code != 200:
        hint = {401: "the key was rejected", 402: "the account is out of credit",
                429: "rate limited, wait and retry"}.get(resp.status_code, "")
        sys.exit(f"Scribe returned {resp.status_code}{' (' + hint + ')' if hint else ''}: "
                 f"{resp.text[:300]}\nNothing was cached; re-run lc intake to retry.")

    return resp.json()


def transcribe_one(
    video: Path,
    edit_dir: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
    verbose: bool = True,
) -> Path:
    """Transcribe a single video. Returns path to transcript JSON.

    Cached: returns existing path immediately if the transcript already exists.
    """
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    if verbose:
        print(f"  extracting audio from {video.name}", flush=True)

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio)
        size_mb = audio.stat().st_size / (1024 * 1024)
        if verbose:
            print(f"  uploading {video.stem}.wav ({size_mb:.1f} MB)", flush=True)
        payload = call_scribe(audio, api_key, language, num_speakers)

    out_path.write_text(json.dumps(payload, indent=2))
    dt = time.time() - t0

    if verbose:
        kb = out_path.stat().st_size / 1024
        print(f"  saved: {out_path.name} ({kb:.1f} KB) in {dt:.1f}s")
        if isinstance(payload, dict) and "words" in payload:
            n = sum(1 for w in payload["words"] if w.get("type", "word") == "word")
            print(f"    words: {n}")

    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe a video with ElevenLabs Scribe")
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Edit output directory (default: <video_parent>/edit)",
    )
    ap.add_argument(
        "--language",
        type=str,
        default=None,
        help="Optional ISO language code (e.g., 'en'). Omit to auto-detect.",
    )
    ap.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="Optional number of speakers when known. Improves diarization accuracy.",
    )
    ap.add_argument(
        "--backend",
        choices=["auto", "scribe", "local"],
        default="auto",
        help="auto: Scribe when a key exists, local whisper otherwise",
    )
    ap.add_argument("--model", default="large-v3", help="local backend model size")
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")

    edit_dir = (args.edit_dir or (video.parent / "edit")).resolve()

    # The cache comes first, for every backend: a transcript that exists costs
    # nothing, needs no key, and must not be announced as being transcribed.
    out = edit_dir / "transcripts" / f"{video.stem}.json"
    if out.exists():
        print(f"cached: {out.name}  (delete it to transcribe again)")
        return

    backend = args.backend
    if backend == "auto":
        backend = "scribe" if load_api_key(required=False) else "local"
    print(f"  backend: {backend}" + ("  (paid, ElevenLabs; the audio is uploaded)" if backend == "scribe"
                                     else "  (whisper on this machine; nothing leaves it)"))
    if backend == "local":
        import transcribe_local
        lang = None if args.language in (None, "auto") else args.language
        transcribe_local.transcribe(video, out, lang, args.model)
        return

    api_key = load_api_key()
    if args.language == "auto":      # "auto" is our word for "detect"; never send it
        args.language = None

    transcribe_one(
        video=video,
        edit_dir=edit_dir,
        api_key=api_key,
        language=args.language,
        num_speakers=args.num_speakers,
    )


if __name__ == "__main__":
    main()
