import asyncio
import os
import tempfile

from faster_whisper import WhisperModel

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        cache = os.getenv("MODEL_CACHE_DIR", "/tmp/models")
        whisper_cache = os.path.join(cache, "whisper")
        os.makedirs(whisper_cache, exist_ok=True)
        _model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
            download_root=whisper_cache,
        )
    return _model


async def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    def _sync() -> str:
        model = _get_model()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            segments, _ = model.transcribe(tmp_path, language="es", beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            os.unlink(tmp_path)

    return await asyncio.to_thread(_sync)
