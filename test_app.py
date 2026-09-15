import os, tempfile, json, pathlib
os.environ["SEAT_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import app

def test_reserve_and_conflict():
    con = app.db()
    assert app.reserve(con, "L01", "a") is None
    assert "이미" in app.reserve(con, "L01", "b")
    assert "다른 자리" in app.reserve(con, "L02", "a")
    app.cancel(con, "a")
    assert app.reserve(con, "L02", "a") is None

def test_purge_old_days():
    con = app.db()
    con.execute("INSERT OR REPLACE INTO reservations VALUES('2000-01-01','L03','x','t')")
    con.commit()
    app.purge_old_days(con)
    assert con.execute("SELECT COUNT(*) FROM reservations WHERE day='2000-01-01'").fetchone()[0] == 0

def test_seats_inside_crop():
    lay = json.loads(pathlib.Path(app.SEATS_PATH).read_text())
    x0, y0, x1, y1 = lay["crop"]
    assert len(lay["seats"]) == 32 and len({s["id"] for s in lay["seats"]}) == 32
    for s in lay["seats"]:
        assert x0 + 11 <= s["x"] <= x1 - 11 and y0 + 11 <= s["y"] <= y1 - 11
