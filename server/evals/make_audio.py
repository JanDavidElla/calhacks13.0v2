"""Generate the voice test files in evals/audio with macOS `say` and `afconvert`.

Run from server/:  uv run python -m evals.make_audio
"""

import os
import subprocess
import tempfile
import wave
from pathlib import Path

from evals.cases import AUDIO_DIR, VOICE_CASES

# afconvert container and codec for each file extension, at 16 kHz mono (speech quality)
FORMATS = {
    ".wav": ["-f", "WAVE", "-d", "LEI16@16000"],
    ".m4a": ["-f", "m4af", "-d", "aac@16000"],
    ".flac": ["-f", "flac", "-d", "flac@16000"],
    ".aac": ["-f", "adts", "-d", "aac@16000"],
}


def speak(text: str, voice: str, rate: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "speech.aiff"
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", aiff, text], check=True, timeout=60)
        subprocess.run(["afconvert", *FORMATS[out.suffix], "-c", "1", aiff, out], check=True, timeout=60)


def write_bad_files(audio_dir: Path) -> None:
    with wave.open(str(audio_dir / "silence.wav"), "wb") as silence:
        silence.setnchannels(1)
        silence.setsampwidth(2)
        silence.setframerate(16000)
        silence.writeframes(b"\x00\x00" * 16000 * 3)
    # A WAV header followed by random bytes, so it looks like audio but isn't
    (audio_dir / "corrupt.wav").write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + os.urandom(4000))
    (audio_dir / "empty.wav").write_bytes(b"")
    (audio_dir / "notes.m4a").write_text("These are meeting notes, not audio.\n")


def main() -> None:
    audio_dir = Path(AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)
    for case in VOICE_CASES:
        if case.kind != "bad_audio" and case.audio:
            speak(case.request, case.voice, case.rate, audio_dir / case.audio)
    write_bad_files(audio_dir)
    for path in sorted(audio_dir.iterdir()):
        print(f"{path.stat().st_size:>8,} bytes  {path.name}")


if __name__ == "__main__":
    main()
