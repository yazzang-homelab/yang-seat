import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
TZ = ZoneInfo("Asia/Seoul")
DB_PATH = Path(os.environ.get("SEAT_DB", ROOT / "data" / "seats.db"))
USERS_PATH = ROOT / "users.json"
SEATS_PATH = ROOT / "seats.json"
CROP_X, CROP_Y = 20, 20  # floor.png는 1.png를 (20,20)에서 크롭한 것
_LOCK = threading.Lock()


# ---------- data ----------
def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute(
        """CREATE TABLE IF NOT EXISTS reservations(
             day TEXT NOT NULL, seat TEXT NOT NULL, user TEXT NOT NULL,
             created_at TEXT NOT NULL,
             PRIMARY KEY(day, seat), UNIQUE(day, user))"""
    )
    return con


def purge_old_days(con: sqlite3.Connection) -> None:
    # 23:59 이후 첫 요청에서 전날 데이터가 자동 소멸한다 (별도 스케줄러 불필요).
    con.execute("DELETE FROM reservations WHERE day < ?", (today(),))
    con.commit()


def load_reservations(con) -> dict[str, str]:
    rows = con.execute("SELECT seat, user FROM reservations WHERE day=?", (today(),)).fetchall()
    return dict(rows)


def reserve(con, seat: str, user: str) -> str | None:
    with _LOCK:
        purge_old_days(con)
        try:
            con.execute(
                "INSERT INTO reservations VALUES(?,?,?,?)",
                (today(), seat, user, datetime.now(TZ).isoformat()),
            )
            con.commit()
        except sqlite3.IntegrityError:
            taken = load_reservations(con)
            if seat in taken:
                return f"{seat}은(는) 이미 {taken[seat]}님이 선점했습니다."
            return "이미 다른 자리를 선점했습니다. 먼저 취소하세요."
    return None


def cancel(con, user: str) -> None:
    with _LOCK:
        con.execute("DELETE FROM reservations WHERE day=? AND user=?", (today(), user))
        con.commit()


@st.cache_data
def load_users() -> dict[str, str]:
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))


@st.cache_data
def load_seats() -> list[dict]:
    return json.loads(SEATS_PATH.read_text(encoding="utf-8"))["seats"]


# ---------- ui ----------
def login():
    st.title("오피스 자리 선점")
    with st.form("login"):
        uid = st.text_input("ID")
        pw = st.text_input("PW", type="password")
        if st.form_submit_button("로그인", use_container_width=True):
            users = load_users()
            if users.get(uid) == pw:
                st.session_state.user = uid
                st.rerun()
            st.error("ID 또는 PW가 틀렸습니다.")


def seat_map_svg(seats, taken, me) -> str:
    import base64

    img = base64.b64encode((ROOT / "floor.png").read_bytes()).decode()
    w, h = 525, 300
    circles = []
    for s in seats:
        x, y = s["x"] - CROP_X, s["y"] - CROP_Y
        owner = taken.get(s["id"])
        if owner == me:
            fill, label = "#2563eb", "나"
        elif owner:
            fill, label = "#9ca3af", owner[:3]
        else:
            fill, label = "#22c55e", s["id"]
        circles.append(
            f'<g><circle cx="{x}" cy="{y}" r="10" fill="{fill}" stroke="#111" stroke-width="1"/>'
            f'<text x="{x}" y="{y+3}" font-size="7" text-anchor="middle" fill="#fff" '
            f'font-family="sans-serif" font-weight="bold">{label}</text>'
            f'<title>{s["id"]} · {s["zone"]} · {owner or "빈 자리"}</title></g>'
        )
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;display:block;border:1px solid #ddd;border-radius:8px;background:#fff">'
        f'<image href="data:image/png;base64,{img}" width="{w}" height="{h}"/>'
        + "".join(circles)
        + "</svg>"
        '<div style="font:12px sans-serif;margin-top:4px;color:#444">'
        '<span style="color:#22c55e">●</span> 빈 자리 &nbsp;'
        '<span style="color:#9ca3af">●</span> 선점됨 &nbsp;'
        '<span style="color:#2563eb">●</span> 내 자리</div>'
    )


def main():
    st.set_page_config(page_title="자리 선점", page_icon="🪑", layout="wide")
    st.markdown(
        "<style>.block-container{padding-top:1rem;max-width:1100px}"
        "div.stButton>button{width:100%;padding:.6rem 0}</style>",
        unsafe_allow_html=True,
    )
    if "user" not in st.session_state:
        login()
        return

    me = st.session_state.user
    con = db()
    purge_old_days(con)
    seats = load_seats()
    taken = load_reservations(con)
    mine = next((s for s, u in taken.items() if u == me), None)

    top = st.columns([3, 1])
    top[0].subheader(f"{today()} · {me}님")
    if top[1].button("로그아웃"):
        del st.session_state.user
        st.rerun()

    st.caption(f"매일 23:59(KST)에 초기화 · 남은 자리 {len(seats)-len(taken)}/{len(seats)}")

    if mine:
        c = st.columns([3, 1])
        c[0].success(f"오늘 내 자리: **{mine}**")
        if c[1].button("선점 취소", type="primary"):
            cancel(con, me)
            st.rerun()

    components.html(seat_map_svg(seats, taken, me), height=340, scrolling=False)

    st.markdown("#### 자리 선택")
    zones: dict[str, list] = {}
    for s in seats:
        zones.setdefault(s["zone"], []).append(s)
    for zone, zs in zones.items():
        st.markdown(f"**{zone}**")
        cols = st.columns(4)  # 모바일에서 st.columns는 자동 세로 스택된다
        for i, s in enumerate(zs):
            owner = taken.get(s["id"])
            if owner:
                cols[i % 4].button(
                    f"{s['id']} · {'나' if owner == me else owner}", key=s["id"], disabled=True
                )
            elif cols[i % 4].button(f"{s['id']} 선점", key=s["id"], disabled=bool(mine)):
                err = reserve(con, s["id"], me)
                if err:
                    st.error(err)
                else:
                    st.rerun()

    with st.expander("오늘 선점 현황"):
        if taken:
            st.table([{"자리": k, "사용자": v} for k, v in sorted(taken.items())])
        else:
            st.write("아직 선점된 자리가 없습니다.")


main()
