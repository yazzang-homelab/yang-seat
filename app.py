import base64
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
TZ = ZoneInfo("Asia/Seoul")
DB_PATH = Path(os.environ.get("SEAT_DB", ROOT / "data" / "seats.db"))
USERS_PATH = ROOT / "users.json"
SEATS_PATH = ROOT / "seats.json"
_LOCK = threading.Lock()

seat_map = components.declare_component("seat_map", path=str(ROOT / "seatmap"))


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
            return "이미 다른 자리를 선점했습니다. 내 자리를 클릭해 먼저 취소하세요."
    return None


def cancel(con, user: str) -> None:
    with _LOCK:
        con.execute("DELETE FROM reservations WHERE day=? AND user=?", (today(), user))
        con.commit()


@st.cache_data
def load_users() -> dict[str, str]:
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))


@st.cache_data
def load_layout() -> dict:
    return json.loads(SEATS_PATH.read_text(encoding="utf-8"))


@st.cache_data
def floor_b64() -> str:
    return base64.b64encode((ROOT / "floor.png").read_bytes()).decode()


# ---------- ui ----------
def login():
    st.title("오피스 자리 선점")
    with st.form("login"):
        uid = st.text_input("ID")
        pw = st.text_input("PW", type="password")
        if st.form_submit_button("로그인", use_container_width=True):
            if load_users().get(uid) == pw:
                st.session_state.user = uid
                st.rerun()
            st.error("ID 또는 PW가 틀렸습니다.")


def main():
    st.set_page_config(page_title="자리 선점", page_icon="🪑", layout="wide")
    st.markdown(
        "<style>.block-container{padding-top:3.5rem;max-width:1100px}</style>",
        unsafe_allow_html=True,
    )
    if "user" not in st.session_state:
        login()
        return

    me = st.session_state.user
    con = db()
    purge_old_days(con)
    layout = load_layout()
    seats = layout["seats"]
    w, h = layout["crop"][2] - layout["crop"][0], layout["crop"][3] - layout["crop"][1]
    taken = load_reservations(con)
    mine = next((s for s, u in taken.items() if u == me), None)

    top = st.columns([3, 1])
    top[0].markdown(f"### {today()} · {me}님")
    if top[1].button("로그아웃", use_container_width=True):
        del st.session_state.user
        st.rerun()

    msg = f"매일 23:59(KST)에 초기화 · 남은 자리 {len(seats)-len(taken)}/{len(seats)}"
    if mine:
        st.success(f"오늘 내 자리: **{mine}** — 파란 원을 클릭하면 취소됩니다. ({msg})")
    else:
        st.info(f"초록 원을 클릭하면 바로 선점됩니다. ({msg})")

    clicked = seat_map(
        img=floor_b64(), w=w, h=h, seats=seats, taken=taken, me=me, key="map", default=None
    )
    if clicked and clicked.get("nonce") != st.session_state.get("last_nonce"):
        st.session_state.last_nonce = clicked["nonce"]
        seat = clicked["seat"]
        if seat == mine:
            cancel(con, me)
            st.rerun()
        elif mine:
            st.error("이미 다른 자리를 선점했습니다. 내 자리(파란 원)를 클릭해 먼저 취소하세요.")
        else:
            err = reserve(con, seat, me)
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
