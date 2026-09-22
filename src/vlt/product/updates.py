from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateInfo:
    available: bool
    version: str = ""
    url: str = ""
    message: str = ""


class UpdateChecker:
    """Replaceable update source. Checks only; installation always stays user controlled."""

    def __init__(self, releases_api: str = ""):
        self.releases_api = releases_api

    def check(self, current_version: str) -> UpdateInfo:
        if not self.releases_api:
            return UpdateInfo(False, message="尚未設定更新來源。")
        request = urllib.request.Request(self.releases_api, headers={"User-Agent": "VtuberLiveTranslator"})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
        version = str(payload.get("tag_name", "")).lstrip("v")
        url = str(payload.get("html_url", ""))
        return UpdateInfo(_version_tuple(version) > _version_tuple(current_version), version, url)


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()

