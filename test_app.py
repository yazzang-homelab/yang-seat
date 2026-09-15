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
    seats = lay["seats"]
    assert len(seats) == 45 and len({s["id"] for s in seats}) == 45
    from collections import Counter
    assert Counter(s["zone"] for s in seats) == {"LSS": 13, "SCC": 14, "CSO": 17, "CGM": 1}
    w, h = x1 - x0, y1 - y0
    for s in seats:
        assert 24 <= s["x"] <= w - 24 and 22 <= s["y"] <= h - 22
    # 박스가 서로 겹치지 않는다
    for a in seats:
        for b in seats:
            if a["id"] < b["id"]:
                assert abs(a["x"] - b["x"]) >= 44 or abs(a["y"] - b["y"]) >= 40, (a["id"], b["id"])


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


def test_csv_import_export():
    con = fresh()
    app.upsert_user(con, "kim", alias="옛별칭")
    app.set_pw(con, "kim", "0420")
    csv = "\ufeffid,alias\nkim,김철수\nlee,이영희\n\npark,\nlee,이영희2\n  \n".encode("utf-8")
    res = app.import_users_csv(con, csv)
    assert res["rows"] == 3 and set(res["added"]) == {"lee", "park"} and res["updated"] == ["kim"]
    assert app.auth(con, "kim", "0420")["name"] == "김철수"       # PW 유지, 별칭 갱신
    assert app.needs_setup(con, "lee") and app.needs_setup(con, "park")
    assert app.user_row(con, "lee")["alias"] == "이영희2"           # 파일 내 중복은 마지막 행
    assert app.user_row(con, "park")["alias"] == ""
    out = app.export_users_csv(con).decode("utf-8-sig").splitlines()
    assert out[0] == "id,alias" and "lee,이영희2" in out and "park," in out and "yang," in out
    # 내려받은 파일을 그대로 다시 올려도 변화 없음(멱등)
    res2 = app.import_users_csv(con, app.export_users_csv(con))
    assert res2["added"] == [] and len(res2["updated"]) == 4
    # 헤더 없는 파일도 됨
    res3 = app.import_users_csv(con, b"choi,\n")
    assert res3["added"] == ["choi"]
