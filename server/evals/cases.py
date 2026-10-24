from dataclasses import dataclass
from typing import Literal

AUDIO_DIR = "evals/audio"

Kind = Literal["pc", "general", "reject", "bad_audio"]


@dataclass(frozen=True)
class Case:
    name: str
    kind: Kind
    request: str = ""              # typed text, or the sentence spoken in the audio file
    budget: float | None = None    # budget the agent should read from the request
    audio: str | None = None       # file in AUDIO_DIR; None means a text request
    transcribe_only: bool = False  # True: check transcription only, skipping the API (no Apify credit)
    voice: str = "Samantha"        # macOS `say` voice used to generate the audio
    rate: int = 175                # speaking rate in words per minute


TEXT_CASES = [
    Case("text_gaming_pc_800", "pc", "Build me a gaming PC for 800 dollars", budget=800),
    Case("text_christmas_200", "general", "I need Christmas stuff for my apartment, $200", budget=200),
    Case("text_nature_room_150", "general", "I need to fill my room with nature items, budget 150 dollars",
         budget=150),
    Case("text_reject_weather", "reject", "What's the weather like in Berkeley today?"),
    Case("text_reject_impossible", "reject", "Build me a gaming PC for $50"),
]

VOICE_CASES = [
    # Sent through the API; rejected requests and bad audio stop before any Apify search
    Case("voice_pc_600", "pc", "I want to make a PC setup with a budget of 600 dollars",
         budget=600, audio="pc_600.wav"),
    Case("voice_office_250", "general", "I need a desk and an office chair for 250 dollars",
         budget=250, audio="office_250.m4a", voice="Daniel"),
    Case("voice_headset_150", "general", "I'd like a gaming headset and a mouse for 150 dollars",
         budget=150, audio="headset_150.aac", voice="Karen", rate=230),
    Case("voice_reject_weather", "reject", "What's the weather like in Berkeley today?",
         audio="weather.wav", voice="Tessa"),
    # Transcription only: accents, speeds, number phrasing and formats
    Case("voice_editing_pc_slow", "pc", "I need a video editing computer for eight hundred and fifty dollars",
         budget=850, audio="editing_pc_slow.flac", voice="Moira", rate=120, transcribe_only=True),
    Case("voice_laptop_fast", "general", "Find me a laptop for college under one thousand two hundred dollars",
         budget=1200, audio="laptop_fast.m4a", voice="Rishi", rate=260, transcribe_only=True),
    # Bad input: the API should fail cleanly, never crash
    Case("bad_silence", "bad_audio", audio="silence.wav"),
    Case("bad_corrupt", "bad_audio", audio="corrupt.wav"),
    Case("bad_empty_file", "bad_audio", audio="empty.wav"),
    Case("bad_not_audio", "bad_audio", audio="notes.m4a"),
]
