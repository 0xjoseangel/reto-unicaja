import asyncio
import io
import os
import urllib.request
import wave

import numpy as np
from piper.voice import PiperVoice

VOICE_NAME = "es_ES-davefx-medium"
_HF_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main"
    "/es/es_ES/davefx/medium"
)

_voice: PiperVoice | None = None


def _ensure_model(cache_dir: str) -> tuple[str, str]:
    os.makedirs(cache_dir, exist_ok=True)
    onnx_path = os.path.join(cache_dir, f"{VOICE_NAME}.onnx")
    cfg_path  = os.path.join(cache_dir, f"{VOICE_NAME}.onnx.json")
    for local, remote in [
        (onnx_path, f"{_HF_BASE}/{VOICE_NAME}.onnx"),
        (cfg_path,  f"{_HF_BASE}/{VOICE_NAME}.onnx.json"),
    ]:
        if not os.path.exists(local):
            print(f"[TTS] Descargando {os.path.basename(local)}...")
            urllib.request.urlretrieve(remote, local)
            print(f"[TTS] Descargado {os.path.basename(local)}")
    return onnx_path, cfg_path


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        cache = os.path.join(os.getenv("MODEL_CACHE_DIR", "/tmp/models"), "piper")
        onnx_path, cfg_path = _ensure_model(cache)
        _voice = PiperVoice.load(onnx_path, config_path=cfg_path, use_cuda=False)
    return _voice


async def synthesize(text: str) -> bytes:
    def _sync() -> bytes:
        voice = _get_voice()
        buf = io.BytesIO()
        wav_file = wave.open(buf, "wb")
        wav_file.setnchannels(1)
        wav_file.setframerate(voice.config.sample_rate)
        wav_file.setsampwidth(2)  # 16-bit PCM
        for chunk in voice.synthesize(text):
            # audio_float_array es float32 en rango [-1, 1]; convertir a int16
            audio_int16 = (chunk.audio_float_array * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        wav_file.close()
        return buf.getvalue()

    return await asyncio.to_thread(_sync)
