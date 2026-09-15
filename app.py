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

import store

ROOT = Path(__file__).parent
TZ = ZoneInfo("Asia/Seoul")
DB_PATH = Path(os.environ.get("SEAT_DB", ROOT / "data" / "seats.db"))
USERS_PATH = ROOT / "users.json"
SEATS_PATH = ROOT / "seats.json"
_LOCK = threading.RLock()

seat_map = components.declare_component("seat_map", path=str(ROOT / "seatmap"))


# ---------- data ----------
def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


@st.cache_resource
def db() -> sqlite3.Connection:
    # 프로세스 내 단일 연결 — 세션마다 연결을 열면 동시 쓰기에서 "database is locked"가 난다
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    con.execute(
        """CREATE TABLE IF NOT EXISTS reservations(
             day TEXT NOT NULL, seat TEXT NOT NULL, user TEXT NOT NULL,
             created_at TEXT NOT NULL,
             PRIMARY KEY(day, seat), UNIQUE(day, user))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS users(
             id TEXT PRIMARY KEY, pw TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0,
             alias TEXT NOT NULL DEFAULT '')"""
    )
    # 구버전 DB(alias 컬럼 없음) 마이그레이션
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
    if "alias" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN alias TEXT NOT NULL DEFAULT ''")
    restore(con)
    return con


def restore(con: sqlite3.Connection) -> None:
    """프로세스 시작 시 gist 스냅샷(있으면) → 없으면 users.json 시드."""
    snap = None
    try:
        snap = store.load()
    except Exception as e:  # gist 장애 시에도 앱은 떠야 한다
        print("gist load failed:", e)
    if snap:
        con.executemany(
            "INSERT OR REPLACE INTO users VALUES(?,?,?,?)",
            [
                (u, v["pw"], int(v.get("admin", False)), v.get("alias", ""))
                for u, v in snap["users"].items()
            ],
        )
        con.executemany(
            "INSERT OR IGNORE INTO reservations VALUES(?,?,?,?)",
            [(r["day"], r["seat"], r["user"], r["created_at"]) for r in snap.get("reservations", [])],
        )
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO users VALUES(?,?,?,?)",
            [
                (u, v["pw"], int(v["admin"]), v.get("alias", ""))
                for u, v in store.bootstrap_users(USERS_PATH).items()
            ],
        )
    purge_old_days(con)


def snapshot(con: sqlite3.Connection) -> None:
    state = {
        "users": {
            u: {"pw": p, "admin": bool(a), "alias": al}
            for u, p, a, al in con.execute("SELECT id, pw, admin, alias FROM users")
        },
        "reservations": [
            dict(zip(("day", "seat", "user", "created_at"), r))
            for r in con.execute("SELECT * FROM reservations")
        ],
    }
    try:
        store.save(state)
    except Exception as e:
        print("gist save failed:", e)


_purged_for = {"day": None}


def purge_old_days(con: sqlite3.Connection) -> None:
    # 날짜가 바뀐 뒤 첫 요청에서 전날 데이터가 소멸한다 (별도 스케줄러 불필요). 하루 1회만 쓴다.
    day = today()
    if _purged_for["day"] == day:
        return
    with _LOCK:
        con.execute("DELETE FROM reservations WHERE day < ?", (day,))
        _purged_for["day"] = day


def load_reservations(con) -> dict[str, str]:
    """{seat: user_id}"""
    rows = con.execute("SELECT seat, user FROM reservations WHERE day=?", (today(),)).fetchall()
    return dict(rows)


def display_names(con) -> dict[str, str]:
    """{user_id: 표시 이름} — 별칭이 있으면 별칭, 없으면 id."""
    return {u: (al or u) for u, al in con.execute("SELECT id, alias FROM users")}


def shown(con, uid: str) -> str:
    return display_names(con).get(uid, uid)


def reserve(con, seat: str, user: str) -> str | None:
    purge_old_days(con)
    with _LOCK:
        try:
            con.execute(
                "INSERT INTO reservations VALUES(?,?,?,?)",
                (today(), seat, user, datetime.now(TZ).isoformat()),
            )
        except sqlite3.IntegrityError:
            taken = load_reservations(con)
            if seat in taken:
                return f"{seat}은(는) 이미 {shown(con, taken[seat])}님이 선점했습니다."
            return "이미 다른 자리를 선점했습니다. 내 자리를 클릭해 먼저 취소하세요."
        snapshot(con)
    return None


def cancel(con, user: str) -> None:
    with _LOCK:
        con.execute("DELETE FROM reservations WHERE day=? AND user=?", (today(), user))
        snapshot(con)


# --- users ---
def auth(con, uid: str, pw: str) -> dict | None:
    row = con.execute("SELECT id, pw, admin, alias FROM users WHERE id=?", (uid,)).fetchone()
    if row and row[1] == pw:
        return {"id": row[0], "admin": bool(row[2]), "name": row[3] or row[0]}
    return None


def list_users(con) -> list[dict]:
    return [
        {"id": u, "pw": p, "admin": bool(a), "alias": al}
        for u, p, a, al in con.execute("SELECT id, pw, admin, alias FROM users ORDER BY admin DESC, id")
    ]


def upsert_user(con, uid: str, pw: str, admin: bool = False, alias: str = "") -> None:
    with _LOCK:
        con.execute(
            "INSERT OR REPLACE INTO users VALUES(?,?,?,?)", (uid, pw, int(admin), alias.strip())
        )
        snapshot(con)


def delete_user(con, uid: str) -> None:
    with _LOCK:
        con.execute("DELETE FROM users WHERE id=?", (uid,))
        con.execute("DELETE FROM reservations WHERE user=?", (uid,))
        snapshot(con)


@st.cache_data
def load_layout() -> dict:
    return json.loads(SEATS_PATH.read_text(encoding="utf-8"))


@st.cache_data
def floor_b64() -> str:
    return base64.b64encode((ROOT / "floor.png").read_bytes()).decode()


# ---------- ui ----------
def login(con, title: str):
    st.title(title)
    with st.form("login"):
        uid = st.text_input("ID")
        pw = st.text_input("PW", type="password")
        if st.form_submit_button("로그인", use_container_width=True):
            u = auth(con, uid.strip(), pw)
            if u:
                st.session_state.user = u
                st.rerun()
            st.error("ID 또는 PW가 틀렸습니다.")


def is_admin_route() -> bool:
    # /?page=admin 으로 직접 진입하거나, 로그인 후 버튼으로 전환
    if st.query_params.get("page") == "admin":
        st.session_state.view = "admin"
        st.query_params.clear()
    return st.session_state.get("view") == "admin"


def goto(view: str) -> None:
    st.session_state.view = view
    st.rerun()


def admin_page(con, me: dict):
    if not me["admin"]:
        st.error("관리자 권한이 없습니다.")
        if st.button("자리 선점으로"):
            goto("seat")
        return
    top = st.columns([3, 1])
    top[0].markdown(f"### 관리자 · {me['id']}")
    if top[1].button("로그아웃", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    if st.button("← 자리 선점 화면"):
        goto("seat")

    st.markdown("#### 계정 추가 / 수정")
    st.caption("같은 ID로 저장하면 PW·별칭·관리자 여부가 덮어써집니다. 별칭이 있으면 화면에 ID 대신 별칭이 보입니다.")
    with st.form("add", clear_on_submit=True):
        c = st.columns([2, 2, 2, 1])
        uid = c[0].text_input("ID")
        pw = c[1].text_input("PW")
        alias = c[2].text_input("별칭 (선택)", placeholder="예: 김철수")
        adm = c[3].checkbox("관리자")
        if st.form_submit_button("저장", use_container_width=True):
            uid = uid.strip()
            if not uid or not pw:
                st.error("ID와 PW를 모두 입력하세요.")
            else:
                upsert_user(con, uid, pw, adm, alias)
                st.success(f"{uid} 저장됨")
                st.rerun()

    st.markdown("#### 계정 목록")
    users = list_users(con)
    st.caption(f"{len(users)}명 · 삭제하면 그 사용자의 오늘 예약도 함께 삭제됩니다.")
    for u in users:
        c = st.columns([2, 2, 1, 1])
        label = f"**{u['alias']}** ({u['id']})" if u["alias"] else f"**{u['id']}**"
        c[0].write(label + (" 👑" if u["admin"] else ""))
        c[1].code(u["pw"], language=None)
        if u["id"] == me["id"]:
            c[3].button("본인", key=f"d-{u['id']}", disabled=True, use_container_width=True)
        elif c[3].button("삭제", key=f"d-{u['id']}", use_container_width=True):
            delete_user(con, u["id"])
            st.rerun()

    with st.expander("오늘 선점 현황 / 강제 해제"):
        taken = load_reservations(con)
        names = display_names(con)
        if not taken:
            st.write("아직 선점된 자리가 없습니다.")
        for seat, user in sorted(taken.items()):
            c = st.columns([1, 2, 1])
            c[0].write(seat)
            c[1].write(names.get(user, user) if names.get(user, user) == user else f"{names[user]} ({user})")
            if c[2].button("해제", key=f"r-{seat}", use_container_width=True):
                cancel(con, user)
                st.rerun()

    if not store.enabled():
        st.warning(
            "GIST_ID / GITHUB_TOKEN 시크릿이 없어 계정·예약이 이 프로세스 안에만 저장됩니다. "
            "Streamlit Cloud에서는 재배포 시 초기화되니 README의 영속화 설정을 따르세요."
        )


def seat_page(con, me: dict):
    layout = load_layout()
    seats = layout["seats"]
    w, h = layout["crop"][2] - layout["crop"][0], layout["crop"][3] - layout["crop"][1]
    top = st.columns([3, 1])
    top[0].markdown(f"### {today()} · {me['name']}님")
    if top[1].button("로그아웃", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    if me["admin"] and st.button("관리자 페이지 (계정 관리)"):
        goto("admin")
    board(con, me["id"], seats, w, h)


@st.fragment(run_every=10)  # 10초마다 DB를 다시 읽어 다른 사람의 선점을 반영
def board(con, me, seats, w, h):
    taken = load_reservations(con)
    mine = next((s for s, u in taken.items() if u == me), None)
    msg = f"매일 23:59(KST)에 초기화 · 남은 자리 {len(seats)-len(taken)}/{len(seats)} · 10초마다 자동 갱신"
    if mine:
        st.success(f"오늘 내 자리: **{mine}** — 파란 원을 클릭하면 취소됩니다. ({msg})")
    else:
        st.info(f"초록 원을 클릭하면 바로 선점됩니다. ({msg})")

    names = display_names(con)
    clicked = seat_map(
        img=floor_b64(), w=w, h=h, seats=seats,
        taken={s: names.get(u, u) for s, u in taken.items()},  # 화면엔 표시 이름
        me=names.get(me, me), key="map", default=None,
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
            st.table([{"자리": k, "사용자": names.get(v, v)} for k, v in sorted(taken.items())])
        else:
            st.write("아직 선점된 자리가 없습니다.")


def main():
    st.set_page_config(page_title="자리 선점", page_icon="🪑", layout="wide")
    st.markdown(
        "<style>.block-container{padding-top:3.5rem;max-width:1100px}</style>",
        unsafe_allow_html=True,
    )
    con = db()
    purge_old_days(con)
    admin_route = is_admin_route()
    if "user" not in st.session_state:
        login(con, "관리자 로그인" if admin_route else "오피스 자리 선점")
        return
    if admin_route:
        admin_page(con, st.session_state.user)
    else:
        seat_page(con, st.session_state.user)


main()
