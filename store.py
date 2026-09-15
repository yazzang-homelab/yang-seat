"""영속 저장소.

Streamlit Community Cloud는 재시작·재배포마다 디스크가 초기화되므로 로컬 SQLite만으로는
관리자가 추가한 계정이 사라진다. 상태(계정 + 오늘 예약)를 GitHub Gist 한 파일에 미러링한다.

- 원본(source of truth)은 프로세스 내 SQLite: 원자적 제약(자리 1인, 1인 1자리)을 DB가 보장.
- 변경 직후 gist에 스냅샷을 쓰고, 프로세스 시작 시 gist에서 복원한다.
- secrets/env에 GIST_ID·GITHUB_TOKEN이 없으면 로컬 파일만 쓴다(개발 모드).
"""

import json
import os
import urllib.request
from pathlib import Path

FILE_NAME = "seat_state.json"


def _cfg(key: str) -> str | None:
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st

        return st.secrets.get(key)  # type: ignore[return-value]
    except Exception:
        return None


def enabled() -> bool:
    return bool(_cfg("GIST_ID") and _cfg("GITHUB_TOKEN"))


def _req(method: str, body: dict | None = None):
    url = f"https://api.github.com/gists/{_cfg('GIST_ID')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_cfg('GITHUB_TOKEN')}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "yang-seat")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def load() -> dict | None:
    """gist 스냅샷을 반환. 미설정·미존재면 None."""
    if not enabled():
        return None
    g = _req("GET")
    f = g.get("files", {}).get(FILE_NAME)
    if not f:
        return None
    content = f.get("content")
    if f.get("truncated"):
        with urllib.request.urlopen(f["raw_url"], timeout=15) as r:
            content = r.read().decode()
    return json.loads(content) if content else None


def save(state: dict) -> None:
    if not enabled():
        return
    _req("PATCH", {"files": {FILE_NAME: {"content": json.dumps(state, ensure_ascii=False, indent=1)}}})


def bootstrap_users(path: Path) -> dict[str, dict]:
    """저장소의 users.json — 최초 1회 시드용."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        uid: (v if isinstance(v, dict) else {"pw": v, "admin": False}) for uid, v in raw.items()
    }
