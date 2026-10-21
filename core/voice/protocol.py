"""Bounded voice transport: 16 kHz mono PCM input, ephemeral PCM output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VOICE_ID = "e4a66454f7a44f63a2cc9e8c044d701d"
MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"


class VoiceParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VoiceStart(VoiceParameters):
    session_id: str = Field(min_length=1, max_length=128)


class VoiceReference(VoiceParameters):
    voice_id: str = Field(min_length=1, max_length=128)


class VoiceFrame(VoiceReference):
    sequence: int = Field(ge=1)
    pcm: str = Field(min_length=1368, max_length=1368)


class VoicePoll(VoiceReference):
    playing: bool = False
    after: int = Field(ge=0)


class VoiceMute(VoiceReference):
    muted: bool


class VoiceOptions(VoiceParameters):
    fish_model: Literal["s2.1-pro", "s2.1-pro-free"] = "s2.1-pro-free"
    silence_ms: int = Field(default=700, ge=300, le=2000)


class VoiceStatus(BaseModel):
    voice_id: str = ""
    session_id: str = ""
    state: Literal["off", "loading", "listening", "thinking", "speaking", "muted", "error"] = "off"
    model_ready: bool = False
    downloading: bool = False
    fish_configured: bool = False
    silence_ms: int = 700
    error: str = ""
    fish_model: Literal["s2.1-pro", "s2.1-pro-free"] = "s2.1-pro-free"
    reference_id: str = VOICE_ID


class VoiceEvent(BaseModel):
    voice_id: str
    session_id: str
    turn_id: str = ""
    round_id: int
    sequence: int
    kind: Literal["interrupt", "transcript", "audio", "audio.end", "error"]
    text: str = ""
    pcm: str = ""
    sample_rate: int = 24000
