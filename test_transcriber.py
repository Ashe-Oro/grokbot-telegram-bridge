#!/usr/bin/env python3
"""Offline ffmpeg decode tests; needs numpy and ffmpeg, no Whisper model or venv."""
import os, subprocess, sys, tempfile, unittest
from unittest.mock import patch
import transcriber

class TestDecode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "sine.ogg")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=3", "-c:a", "libopus", cls.path], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_short_clip_decodes(self):
        audio = transcriber.decode(self.path)
        self.assertEqual(audio.dtype, transcriber.np.dtype("float32"))
        self.assertEqual(audio.ndim, 1)
        self.assertAlmostEqual(audio.size, 3 * 16000, delta=160)

    def test_pcm_byte_ceiling(self):
        processes = []
        popen = subprocess.Popen
        def start(*a, **kw):
            p = popen(*a, **kw)
            processes.append(p)
            return p
        with patch.object(transcriber, "MAX_PCM_BYTES", 1024), \
             patch.object(transcriber.subprocess, "Popen", side_effect=start):
            with self.assertRaisesRegex(RuntimeError, "decoded audio too large"):
                transcriber.decode(self.path)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)

    def test_duration_cap(self):
        with patch.object(transcriber, "MAX_SECONDS", 0.25):
            audio = transcriber.decode(self.path)
        self.assertAlmostEqual(audio.size, 0.25 * 16000, delta=160)

    def test_ffmpeg_argv_limits(self):
        argv = transcriber.decode_argv(self.path)
        self.assertEqual(argv[argv.index("-protocol_whitelist") + 1], "file,pipe")
        self.assertLess(argv.index("-protocol_whitelist"), argv.index("-i"))
        self.assertGreater(argv.index("-t"), argv.index("-i"))
        self.assertEqual(float(argv[argv.index("-t") + 1]), transcriber.MAX_SECONDS)

    def test_decode_timeout_kills_process(self):
        processes = []
        popen = subprocess.Popen
        def start(*a, **kw):
            p = popen(*a, **kw)
            processes.append(p)
            return p
        with patch.object(transcriber, "DECODE_TIMEOUT", 0.1), \
             patch.object(transcriber, "decode_argv", return_value=[sys.executable, "-c", "import time; time.sleep(30)"]), \
             patch.object(transcriber.subprocess, "Popen", side_effect=start):
            with self.assertRaises(subprocess.TimeoutExpired):
                transcriber.decode(self.path)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)

    def test_invalid_audio(self):
        with self.assertRaisesRegex(RuntimeError, "ffmpeg decode failed"):
            transcriber.decode(os.path.join(self.tmp.name, "missing.ogg"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
