import os, tempfile, json, pathlib
os.environ["SEAT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import app

def test_reserve_and_conflict():
    con = app.db()
    assert app.reserve(con, "L01", "a") is None
    assert "이미" in app.reserve(con, "L01", "b")      # 같은 자리
    assert "다른 자리" in app.reserve(con, "L02", "a")  # 1인 1좌석
    app.cancel(con, "a")
    assert app.reserve(con, "L02", "a") is None

def test_purge_old_days():
    con = app.db()
    con.execute("INSERT OR REPLACE INTO reservations VALUES('2000-01-01','L03','x','t')")
    con.commit()
    app.purge_old_days(con)
    assert con.execute("SELECT COUNT(*) FROM reservations WHERE day='2000-01-01'").fetchone()[0] == 0

def test_seats_inside_crop():
    seats = json.loads(pathlib.Path(app.SEATS_PATH).read_text())["seats"]
    assert len(seats) == 32
    assert len({s["id"] for s in seats}) == 32
    for s in seats:
        assert 0 <= s["x"] - app.CROP_X <= 525 and 0 <= s["y"] - app.CROP_Y <= 300
