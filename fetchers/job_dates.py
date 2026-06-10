from datetime import datetime, timezone


def extract_posted_at(ats_type: str, raw_data: dict) -> datetime | None:
    if ats_type == "greenhouse":
        return _parse_iso(raw_data.get("updated_at") or raw_data.get("first_published"))

    if ats_type == "lever":
        created_ms = raw_data.get("createdAt")
        if created_ms is not None:
            try:
                return datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return None

    if ats_type == "ashby":
        return _parse_iso(
            raw_data.get("publishedAt")
            or raw_data.get("updatedAt")
            or raw_data.get("createdAt")
        )

    if ats_type == "workable":
        return _parse_iso(raw_data.get("published_on") or raw_data.get("created_at"))

    if ats_type == "smartrecruiters":
        return _parse_iso(raw_data.get("releasedDate"))

    if ats_type == "teamtailor":
        return _parse_iso(raw_data.get("pubDate"))

    if ats_type == "workday":
        return _parse_iso(raw_data.get("postedOn"))

    return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
