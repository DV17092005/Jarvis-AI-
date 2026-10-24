"""
jarvis_brain.py - Hybrid Cloud + Offline AI Brain with Rate Limit Failover
Uses free Groq endpoints for ultra-fast responses, and smoothly falls back
to offline local processing if API rate limits or network issues occur.
"""

import os
import json
import time
import re
import logging
import tempfile
from openai import OpenAI
import jarvis_actions

KEYFILE = os.path.expanduser("~/.openjarvis/free.key")
MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"]

_client = None
_client_key = None
_available_models = None
_preferred_model = None
_authentication_error = None
_history = []
_cooldown_until = 0.0
_logger = logging.getLogger("jarvis.brain")

SYSTEM_PROMPT = """You are Jarvis, a fast, highly capable AI executive assistant running on the user's computer.
Use an original, calm, polished, and technically precise voice. Be warm and direct,
with occasional understated humor only when it fits. Respond in 1-2 concise
sentences. Avoid filler, stiff corporate language, stock catchphrases, and
imitating any existing fictional character or using dialogue from their works.
"""


def _get_api_key():
    environment_key = os.environ.get("GROQ_API_KEY", "").strip()
    if environment_key:
        return environment_key
    if os.path.exists(KEYFILE):
        with open(KEYFILE, encoding="utf-8") as keyfile:
            return keyfile.read().strip()
    return None


def api_key_status():
    if os.environ.get("GROQ_API_KEY", "").strip():
        return {"configured": True, "source": "environment"}
    if _get_api_key():
        return {"configured": True, "source": "local_file"}
    return {"configured": False, "source": "none"}


def connection_error():
    return _authentication_error


def save_api_key(api_key):
    global _client, _client_key, _available_models, _preferred_model, _authentication_error, _cooldown_until, _history

    if os.environ.get("GROQ_API_KEY", "").strip():
        raise RuntimeError("GROQ_API_KEY environment variable takes precedence over the saved key")
    current_key = _get_api_key()

    config_dir = os.path.dirname(KEYFILE)
    os.makedirs(config_dir, mode=0o700, exist_ok=True)
    if os.name != "nt":
        os.chmod(config_dir, 0o700)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_dir,
            prefix=".free.key-",
            delete=False,
        ) as keyfile:
            temp_path = keyfile.name
            keyfile.write(api_key)
            keyfile.flush()
            os.fsync(keyfile.fileno())
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, KEYFILE)
        temp_path = None
        _cooldown_until = 0.0
        _authentication_error = None
        if current_key != api_key:
            _client = None
            _client_key = None
            _available_models = None
            _preferred_model = None
            _history = []
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def delete_api_key():
    global _client, _client_key, _available_models, _preferred_model, _authentication_error, _cooldown_until, _history

    existed = os.path.exists(KEYFILE)
    if existed:
        os.remove(KEYFILE)
    _cooldown_until = 0.0
    _authentication_error = None
    _client = None
    _client_key = None
    _available_models = None
    _preferred_model = None
    _history = []
    return existed


def ready():
    """Returns True if the cloud brain is active and not currently rate-limited."""
    key = _get_api_key()
    return bool(key and key == _client_key and _preferred_model and time.time() >= _cooldown_until)


class GroqConnectionError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _get_client(key):
    global _client, _client_key, _available_models, _preferred_model, _history

    if _client is None or _client_key != key:
        _client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        _client_key = key
        _available_models = None
        _preferred_model = None
        _history = []
    return _client


def _chat_model_ids(models):
    unsupported = ("embed", "whisper", "tts", "speech", "guard", "safeguard", "moderation", "rerank")
    identifiers = [
        model.id
        for model in models
        if isinstance(getattr(model, "id", None), str)
        and model.id
        and not any(part in model.id.lower() for part in unsupported)
    ]
    priority = {model: index for index, model in enumerate(MODELS)}
    ordered = sorted(dict.fromkeys(identifiers), key=lambda model: (priority.get(model, len(priority)), model))
    return ordered[:5]


def _connection_error(error):
    status_code = getattr(error, "status_code", None)
    if status_code == 401:
        return GroqConnectionError(
            "Groq rejected this API key (401). Replace it with an active key from the Groq console.",
            status_code,
        )
    if status_code == 403:
        return GroqConnectionError(
            "Groq denied access to this API key (403). Check the key and account permissions.",
            status_code,
        )
    if status_code == 429:
        return GroqConnectionError(
            "Groq rate limit reached (429). Wait for the limit to reset, then test again.",
            status_code,
        )
    if status_code is not None:
        return GroqConnectionError(
            f"Groq returned HTTP {status_code} while checking the connection.",
            status_code,
        )
    return GroqConnectionError("Could not reach Groq. Check your internet connection and try again.")


def _refresh_available_models(client):
    global _available_models, _authentication_error

    try:
        _available_models = _chat_model_ids(client.models.list().data)
    except Exception as error:
        safe_error = _connection_error(error)
        if safe_error.status_code in (401, 403):
            _authentication_error = str(safe_error)
        raise safe_error from None
    if not _available_models:
        raise GroqConnectionError("Groq returned no available chat models.")
    return _available_models


def test_connection():
    """Verify the configured Groq key and find an active chat model."""
    global _available_models, _preferred_model, _authentication_error

    key = _get_api_key()
    if not key:
        raise GroqConnectionError("Add a Groq API key before testing the connection.")

    _authentication_error = None
    _available_models = None
    _preferred_model = None
    client = _get_client(key)
    models = _refresh_available_models(client)
    last_error = None
    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=8,
                temperature=0.2,
            )
            if not (response.choices[0].message.content or "").strip():
                continue
            _preferred_model = model
            return {"connected": True, "model": model}
        except Exception as error:
            last_error = error
            status_code = getattr(error, "status_code", None)
            if status_code in (401, 403, 429):
                safe_error = _connection_error(error)
                if status_code in (401, 403):
                    _authentication_error = str(safe_error)
                raise safe_error from None

    if last_error is not None:
        raise _connection_error(last_error) from None
    raise GroqConnectionError("Groq models were listed, but none returned a chat response.")


def transcribe_audio(audio_data, filename, content_type, language):
    global _authentication_error

    key = _get_api_key()
    if not key:
        raise GroqConnectionError("Add and verify a Groq API key before using voice input.", 503)

    client = _get_client(key)
    try:
        result = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=(filename, audio_data, content_type),
            language=language,
            response_format="json",
        )
    except Exception as error:
        status_code = getattr(error, "status_code", None)
        if status_code in (401, 403):
            safe_error = _connection_error(error)
            _authentication_error = str(safe_error)
            raise safe_error from None
        if status_code == 429:
            raise _connection_error(error) from None
        _logger.warning("Groq speech transcription failed with HTTP %s", status_code or "unknown")
        raise GroqConnectionError("Groq could not transcribe this audio. Try again or type your command.") from None

    text = (getattr(result, "text", None) or "").strip()
    if not text:
        raise GroqConnectionError("No speech was recognized. Try again closer to the microphone.")
    return text


def _is_rate_limited(e):
    status = getattr(e, "status_code", None)
    if status == 429:
        return True
    s = str(e).lower()
    return any(w in s for w in ("429", "rate limit", "too many requests", "rate_limit", "exceeded"))


def _retry_after_seconds(e, default=60):
    s = str(e).lower()
    m = re.search(r"try again in\s*(\d+)m\s*([0-9]+(?:\.[0-9]+)?)s", s)
    if m:
        return int(float(m.group(1)) * 60 + float(m.group(2))) + 2
    m = re.search(r"try again in\s*([0-9]+(?:\.[0-9]+)?)s", s)
    if m:
        return int(float(m.group(1))) + 2
    return default


def _set_cooldown(secs):
    global _cooldown_until
    _cooldown_until = max(_cooldown_until, time.time() + float(secs))


def _local_fallback():
    if time.time() < _cooldown_until:
        return (
            "The Groq service is temporarily rate-limited. Local commands still work; "
            "for general questions, wait for the cooldown or check your API plan."
        )
    if not _get_api_key():
        return (
            "Cloud AI is not configured yet. Add a Groq API key as GROQ_API_KEY to enable "
            "general questions; local commands such as opening apps and searching still work."
        )
    return (
        "Cloud AI is temporarily unavailable. Local commands are still available; "
        "check your internet connection and Groq API key."
    )


def think(q):
    """
    Main entry point for queries. Tries local actions first, then cloud AI,
    with automatic fallback if rate limited.
    """
    global _available_models, _preferred_model, _authentication_error, _history

    # Deterministic actions stay available even without a cloud API key.
    local_done = jarvis_actions.try_action(q)
    if local_done:
        return local_done

    key = _get_api_key()
    if not key or time.time() < _cooldown_until:
        return _local_fallback()
    if _authentication_error:
        return _authentication_error

    client = _get_client(key)
    try:
        if _available_models is None:
            _refresh_available_models(client)
    except GroqConnectionError as error:
        _logger.warning("Groq connection check failed: %s", error)
        return str(error)

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + _history[-6:] + [{"role": "user", "content": q}]

    candidate_models = list(dict.fromkeys(([_preferred_model] if _preferred_model else []) + (_available_models or [])))
    for model in candidate_models:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=msgs,
                max_tokens=350,
                temperature=0.6,
            )
            answer = (resp.choices[0].message.content or "").strip()
            if not answer:
                continue
            _preferred_model = model
            _history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
            return answer
        except Exception as e:
            if _is_rate_limited(e):
                wait_sec = _retry_after_seconds(e)
                _set_cooldown(wait_sec)
                _logger.warning("Groq rate limit reached; retrying after %s seconds", wait_sec)
                return _local_fallback()
            if getattr(e, "status_code", None) in (401, 403):
                _preferred_model = None
                _available_models = None
                safe_error = _connection_error(e)
                _authentication_error = str(safe_error)
                return _authentication_error
            _logger.warning(
                "Groq model %s failed with HTTP %s",
                model,
                getattr(e, "status_code", "unknown"),
            )

    _preferred_model = None
    return "Groq listed chat models, but none returned a response. Check model access and try the connection test again."


if __name__ == "__main__":
    print("Testing Jarvis Brain...")
    print(think("what time is it"))
    print(think("how are you"))
