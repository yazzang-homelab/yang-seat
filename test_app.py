import os, tempfile, json, pathlib
os.environ["SEAT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import app


def fresh():
    app.db.clear()
    os.environ["SEAT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
    app.DB_PATH = pathlib.Path(os.environ["SEAT_DB"])
    return app.db()


def test_reserve_and_conflict():
    con = fresh()
    assert app.reserve(con, "L01", "a") is None
    assert "이미" in app.reserve(con, "L01", "b")
    assert "다른 자리" in app.reserve(con, "L02", "a")
    app.cancel(con, "a")
    assert app.reserve(con, "L02", "a") is None


def test_purge_old_days():
    con = fresh()
    con.execute("INSERT OR REPLACE INTO reservations VALUES('2000-01-01','L03','x','t')")
    app._purged_for["day"] = None
    app.purge_old_days(con)
    assert con.execute("SELECT COUNT(*) FROM reservations WHERE day='2000-01-01'").fetchone()[0] == 0


def test_users_seed_and_admin():
    con = fresh()
    assert app.auth(con, "yang", "1234") == {"id": "yang", "admin": True, "name": "yang"}
    assert app.auth(con, "yang", "x") is None
    assert app.auth(con, "nobody", "1234") is None
    # 신규 등록 = 빈 PW → 첫 접속 설정 흐름
    app.upsert_user(con, "kim", alias=" 김철수 ")
    assert app.needs_setup(con, "kim") and not app.needs_setup(con, "yang") and not app.needs_setup(con, "ghost")
    assert app.auth(con, "kim", "") is None  # 빈 PW로 로그인 불가
    assert "숫자 4자리" in app.set_pw(con, "kim", "12")
    assert "숫자 4자리" in app.set_pw(con, "kim", "abcd")
    assert "숫자 4자리" in app.set_pw(con, "kim", "12345")
    assert app.set_pw(con, "kim", "0420") is None
    assert app.auth(con, "kim", "0420") == {"id": "kim", "admin": False, "name": "김철수"}
    assert "이미 PW" in app.set_pw(con, "kim", "9999")  # 재설정은 관리자 초기화 필요
    # 재저장은 별칭/권한만 갱신, PW 유지
    app.upsert_user(con, "kim", admin=True, alias="김팀장")
    assert app.auth(con, "kim", "0420") == {"id": "kim", "admin": True, "name": "김팀장"}
    # 초기화 → 다시 설정 가능
    app.reset_pw(con, "kim")
    assert app.needs_setup(con, "kim") and app.auth(con, "kim", "0420") is None
    assert app.set_pw(con, "kim", "1111") is None and app.auth(con, "kim", "1111")
    assert app.display_names(con) == {"yang": "yang", "kim": "김팀장"}
    app.reserve(con, "L09", "kim")
    assert "김팀장님이 선점" in app.reserve(con, "L09", "yang")
    app.delete_user(con, "kim")
    assert app.user_row(con, "kim") is None
    assert "L09" not in app.load_reservations(con)


def test_seats_inside_crop():
    lay = json.loads(pathlib.Path(app.SEATS_PATH).read_text())
    x0, y0, x1, y1 = lay["crop"]
    assert len(lay["seats"]) == 32 and len({s["id"] for s in lay["seats"]}) == 32
    for s in lay["seats"]:
        assert x0 + 11 <= s["x"] <= x1 - 11 and y0 + 11 <= s["y"] <= y1 - 11


def test_migrates_old_users_table():
    import sqlite3
    app.db.clear()
    os.environ["SEAT_DB"] = os.path.join(tempfile.mkdtemp(), "old.db")
    app.DB_PATH = pathlib.Path(os.environ["SEAT_DB"])
    old = sqlite3.connect(app.DB_PATH)
    old.execute("CREATE TABLE users(id TEXT PRIMARY KEY, pw TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0)")
    old.execute("INSERT INTO users VALUES('yang','1234',1)")
    old.commit(); old.close()
    con = app.db()
    assert app.auth(con, "yang", "1234") == {"id": "yang", "admin": True, "name": "yang"}
    app.upsert_user(con, "yang", True, "양")
    assert app.auth(con, "yang", "1234")["name"] == "양"  # PW 유지
