import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_RESUME_CHARS = 12_000


def load_resume(path: str) -> str | None:
    resume_path = Path(path)
    if not resume_path.exists():
        logger.info("Resume file not found at %s — resume scoring skipped", resume_path)
        return None

    text = resume_path.read_text(encoding="utf-8").strip()
    if not text:
        logger.warning("Resume file %s is empty — resume scoring skipped", resume_path)
        return None

    if len(text) > MAX_RESUME_CHARS:
        logger.warning(
            "Resume truncated from %d to %d characters for token limits",
            len(text),
            MAX_RESUME_CHARS,
        )
        text = text[:MAX_RESUME_CHARS]

    logger.info("Loaded resume from %s (%d characters)", resume_path, len(text))
    return text
