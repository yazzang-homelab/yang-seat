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
    app.upsert_user(con, "kim", "pw1")
    assert app.auth(con, "kim", "pw1") == {"id": "kim", "admin": False, "name": "kim"}
    app.upsert_user(con, "kim", "pw1", alias=" 김철수 ")
    assert app.auth(con, "kim", "pw1")["name"] == "김철수"
    assert app.display_names(con) == {"yang": "yang", "kim": "김철수"}
    app.reserve(con, "L09", "kim")
    assert "김철수님이 선점" in app.reserve(con, "L09", "yang")
    app.cancel(con, "kim")
    app.upsert_user(con, "kim", "pw2")  # 비번 변경
    assert app.auth(con, "kim", "pw1") is None and app.auth(con, "kim", "pw2")
    app.reserve(con, "L05", "kim")
    app.delete_user(con, "kim")
    assert app.auth(con, "kim", "pw2") is None
    assert "L05" not in app.load_reservations(con)  # 예약도 함께 삭제


def test_seats_inside_crop():
    lay = json.loads(pathlib.Path(app.SEATS_PATH).read_text())
    x0, y0, x1, y1 = lay["crop"]
    assert len(lay["seats"]) == 32 and len({s["id"] for s in lay["seats"]}) == 32
    for s in lay["seats"]:
        assert x0 + 11 <= s["x"] <= x1 - 11 and y0 + 11 <= s["y"] <= y1 - 11
