#!/usr/bin/env python3
"""Long-lived local transcriber for the relay. Runs under the faster-whisper venv
(GROKBOT_ASR_PYTHON, default ./.venv-asr/bin/python), never under the system python.

Protocol: one JSON object per line on stdin {"path": "..."}; one JSON line on stdout
{"ok": true, "text": "...", "language": "en", "duration": 3.2} or {"ok": false, "error": "..."}.
Prints {"ready": true} once the model is loaded. Never logs transcripts.
Audio is decoded with ffmpeg to 16 kHz mono float32 and passed as a numpy array
(on some PyAV/faster-whisper combinations, passing a file path raises
"TypeError: open() got an unexpected keyword argument 'metadata_errors'" inside av.open).
"""
import json, os, subprocess, sys
import numpy as np
from faster_whisper import WhisperModel

MODEL = os.environ.get("GROKBOT_ASR_MODEL") or "base.en"
DECODE_TIMEOUT = 60

def decode(path):
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-f", "f32le",
                        "-ac", "1", "-ar", "16000", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=DECODE_TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg decode failed")
    return np.frombuffer(p.stdout, dtype=np.float32)

def main():
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    out = sys.stdout
    out.write(json.dumps({"ready": True, "model": MODEL}) + "\n"); out.flush()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            audio = decode(req["path"])
            if audio.size == 0:
                raise RuntimeError("no audio")
            segs, info = model.transcribe(audio, beam_size=5, vad_filter=False)
            text = " ".join(s.text.strip() for s in segs).strip()
            res = {"ok": True, "text": text, "language": info.language,
                   "duration": round(float(info.duration), 2)}
        except Exception as e:
            res = {"ok": False, "error": type(e).__name__ + ": " + str(e)[:200]}
        out.write(json.dumps(res) + "\n"); out.flush()

if __name__ == "__main__":
    main()
