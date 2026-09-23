#!/usr/bin/env python3
# extract_audio() is adapted from browser-use/video-use helpers/transcribe.py
# (MIT, Copyright (c) 2026 Browser Use). See THIRD_PARTY_NOTICES.md.
"""Local word-level transcription, for a machine with no ASR API key.

The whole pipeline is built on WORD-level timestamps: a cut is placed between
two specific words, and a caption cue is assembled from the words inside a
range. A segment-level transcript cannot drive any of it. So whatever backend
runs here has to emit words with a start and an end, and the output is written
in the same shape the rest of the toolchain already reads:

    {"language_code": "ar",
     "text": "...",
     "words": [{"text": "…", "start": 12.34, "end": 12.61, "type": "word"}, ...]}

Backends, in the order they are tried:

  faster-whisper   pip install faster-whisper      (CTranslate2, fast on CPU)
  openai-whisper   pip install openai-whisper      (slower, same model weights)

Quality note, stated plainly because it changes what the editorial read can
trust: a local whisper transcript is good enough to place cuts and to find
retakes, and it is NOT as reliable as a paid recogniser on proper nouns, on
mixed-language speech, or on dialect. Every Latin token still has to be checked
against the screen before it reaches a caption, which is the rule anyway.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_audio(video: Path, dest: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(dest)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _faster_whisper(audio: Path, language: str | None, model_size: str) -> dict:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, info = model.transcribe(
        str(audio), language=language, word_timestamps=True,
        vad_filter=False,            # VAD drops the quiet murmurs a cut needs to see
        condition_on_previous_text=False,
    )
    words, text = [], []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"text": w.word.strip(), "start": round(w.start, 3),
                          "end": round(w.end, 3), "type": "word"})
        text.append(seg.text)
        print(f"\r  {seg.end/60:6.1f} min transcribed", end="", flush=True)
    print()
    return {"language_code": info.language, "text": "".join(text), "words": words}


def _openai_whisper(audio: Path, language: str | None, model_size: str) -> dict:
    import whisper

    model = whisper.load_model(model_size)
    res = model.transcribe(str(audio), language=language, word_timestamps=True,
                           condition_on_previous_text=False, verbose=False)
    words = []
    for seg in res.get("segments", []):
        for w in seg.get("words", []):
            words.append({"text": w["word"].strip(), "start": round(w["start"], 3),
                          "end": round(w["end"], 3), "type": "word"})
    return {"language_code": res.get("language"), "text": res.get("text", ""), "words": words}


def available() -> str | None:
    for mod, name in (("faster_whisper", "faster-whisper"), ("whisper", "openai-whisper")):
        try:
            __import__(mod)
            return name
        except ImportError:
            continue
    return None


def transcribe(video: Path, out_path: Path, language: str | None = None,
               model_size: str = "large-v3") -> Path:
    backend = available()
    if backend is None:
        lc_home = os.environ.get("LESSON_CUT_HOME") or os.path.expanduser("~/.lesson-cut")
        scripts = Path(__file__).resolve().parent
        sys.exit("no transcription backend: no ElevenLabs key, and no local ASR in this python.\n"
                 "  either add a key (a private file):\n"
                 f"      (umask 077; mkdir -p \"{lc_home}\" && echo 'ELEVENLABS_API_KEY=sk_...' > \"{lc_home}/env\")\n"
                 "  or install the local recogniser into the lesson-cut venv:\n"
                 f"      bash \"{scripts / 'setup.sh'}\" --local-asr\n"
                 f"  (\"{scripts / 'lc'}\" doctor shows both)")
    print(f"  backend: {backend} ({model_size})")
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.wav"
        print(f"  extracting audio from {video.name}", flush=True)
        extract_audio(video, audio)
        payload = (_faster_whisper(audio, language, model_size) if backend == "faster-whisper"
                   else _openai_whisper(audio, language, model_size))
    if not payload["words"]:
        sys.exit("the transcript came back with no words; nothing downstream can run on it")
    ws, fixed = payload["words"], 0
    for i, w in enumerate(ws):
        if w["end"] <= w["start"]:
            # Whisper sometimes stamps a word with no duration, or several words
            # with one timestamp. A zero-length word cannot be cut on its own,
            # so give it a sliver, never running into the next word.
            nxt = ws[i + 1]["start"] if i + 1 < len(ws) else w["start"] + 0.04
            w["end"] = round(max(w["start"] + 0.02, min(w["start"] + 0.04, nxt)), 3)
            fixed += 1
    if fixed:
        print(f"  {fixed} zero-length word(s) given a 20-40ms span")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"  saved: {out_path.name}  ({len(payload['words'])} words)")
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--language", default=None)
    ap.add_argument("--model", default="large-v3")
    a = ap.parse_args()
    transcribe(a.video.resolve(), a.out.resolve(), a.language, a.model)
