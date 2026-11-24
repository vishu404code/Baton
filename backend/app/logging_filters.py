"""Never log secrets: redact ?token=... (the WebSocket query string) from uvicorn logs."""

import logging
import re

_TOKEN = re.compile(r"((?:token|access_token)=)[^&\s\"']+", re.IGNORECASE)
_BEARER = re.compile(r"\b(bs_|bat_)[A-Za-z0-9_\-]{8,}")


def redact(text: str) -> str:
    return _BEARER.sub(r"\1[redacted]", _TOKEN.sub(r"\1[redacted]", text))


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True


def install() -> None:
    f = RedactTokens()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "baton"):
        logging.getLogger(name).addFilter(f)
