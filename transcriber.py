#!/usr/bin/env python3
"""Long-lived local transcriber for the relay. Runs under the faster-whisper venv
(GROKBOT_ASR_PYTHON, default ./.venv-asr/bin/python). The decode helper can also be
imported under system python with numpy, without loading Whisper.

Protocol: one JSON object per line on stdin {"path": "..."}; one JSON line on stdout
{"ok": true, "text": "...", "language": "en", "duration": 3.2} or {"ok": false, "error": "..."}.
Prints {"ready": true} once the model is loaded. Never logs transcripts.
Audio is decoded with ffmpeg to 16 kHz mono float32 and passed as a numpy array
(on some PyAV/faster-whisper combinations, passing a file path raises
"TypeError: open() got an unexpected keyword argument 'metadata_errors'" inside av.open).
"""
import json, math, os, select, subprocess, sys, time
import numpy as np

MODEL = os.environ.get("GROKBOT_ASR_MODEL") or "base.en"
DECODE_TIMEOUT = 60
MAX_SECONDS = float(os.environ.get("GROKBOT_ASR_MAX_SECONDS") or "600")
MAX_PCM_BYTES = int(os.environ.get("GROKBOT_ASR_MAX_PCM_BYTES") or str(64 * 1024 * 1024))
if not math.isfinite(MAX_SECONDS) or MAX_SECONDS <= 0 or MAX_PCM_BYTES <= 0:
    raise ValueError("ASR decode limits must be positive and finite")

def decode_argv(path):
    return ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-i", path, "-t", str(MAX_SECONDS), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"]

def decode(path):
    argv = decode_argv(path)
    deadline = time.monotonic() + DECODE_TIMEOUT
    data = bytearray()
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as p:
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([p.stdout], [], [], remaining)[0]:
                    raise subprocess.TimeoutExpired(argv, DECODE_TIMEOUT)
                chunk = os.read(p.stdout.fileno(), min(65536, MAX_PCM_BYTES - len(data) + 1))
                if not chunk:
                    break
                if len(data) + len(chunk) > MAX_PCM_BYTES:
                    raise RuntimeError("decoded audio too large")
                data.extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, DECODE_TIMEOUT)
            if p.wait(timeout=remaining) != 0:
                raise RuntimeError("ffmpeg decode failed")
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()
    return np.frombuffer(data, dtype=np.float32)

def main():
    from faster_whisper import WhisperModel
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
