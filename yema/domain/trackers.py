from __future__ import annotations

import base64
import urllib.parse
from typing import Any, List

def get_tracker_display_name(domain: str) -> str:
    """Map tracker domain to a short display name, fallback to domain itself."""
    from yema.tracker_map import TRACKER_DISPLAY_MAP

    return TRACKER_DISPLAY_MAP.get(domain, domain)


def _parse_mteam_detail_url(tracker_urls: List[str]) -> str | None:
    """Extract m-team detail URL from tracker credential (base64 -> tid)."""
    for url in tracker_urls:
        if "tracker.m-team.cc" not in url.lower():
            continue
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            credential_values = params.get("credential")
            if not credential_values:
                return None
            credential = credential_values[0]
            padding = "=" * (-len(credential) % 4)
            decoded = base64.b64decode(credential + padding).decode("utf-8", errors="ignore")
            for part in decoded.split("&"):
                if part.startswith("tid="):
                    tid = part[4:]
                    if tid:
                        return f"https://kp.m-team.cc/detail/{tid}"
        except Exception:
            pass
    return None


def _parse_hhanclub_detail_url(comment: str) -> str | None:
    """Extract hhanclub detail URL from torrent comment field."""
    if not comment:
        return None
    if "hhanclub.net" not in comment.lower():
        return None
    if "details.php?id=" in comment:
        return comment.strip()
    return None


def is_tracker_address(url: str) -> bool:
    lower = url.lower().strip()
    if lower in {"dht", "pex", "lsd"}:
        return False
    if "dht" in lower and "://" not in lower:
        return False
    if "pex" in lower and "://" not in lower:
        return False
    if "lsd" in lower and "://" not in lower:
        return False
    return "://" in lower or lower.startswith("udp:") or lower.startswith("http:") or lower.startswith("https:")


def extract_domain_from_url(url: str) -> str:
    """Extract domain from tracker URL"""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


def extract_yemapt_tracker_user_id(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url)
        if "yemapt.org" not in (parsed.netloc or "").lower():
            return None
        uid_values = urllib.parse.parse_qs(parsed.query).get("uid")
        if not uid_values:
            return None
        uid_encoded = uid_values[0]
        padding = "=" * (-len(uid_encoded) % 4)
        decoded = base64.b64decode(uid_encoded + padding).decode("utf-8", errors="ignore")
        parts = decoded.split("\t")
        if len(parts) >= 3 and parts[2].strip():
            return parts[2].strip()
    except Exception:
        pass
    return None


def normalize_user_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit():
        text = str(int(text))
    return text or None
