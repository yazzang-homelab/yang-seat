# yang-seat — 오피스 자리 선점

Streamlit 단일 파일 앱. 로그인(ID/PW) → 도면 위 32개 좌석 중 하나를 그날 선점. 1인 1좌석, 매일 23:59(KST) 초기화.

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
# 또는
docker build -t yang-seat . && docker run -d -p 8501:8501 -v seatdata:/app/data yang-seat
```

## 파일

| 파일 | 역할 |
|---|---|
| `app.py` | 앱 전체 (로그인·좌석 맵 SVG·선점/취소·SQLite) |
| `seats.json` | 좌석 32개 좌표 (도면 의자 위치에 맞춰 정렬; L=LSS 13, S=SCC 6, C=CSO 13) |
| `users.json` | `{ "id": "pw" }` 계정 목록 — 여기만 고치면 사용자 추가 |
| `floor.png` | 1.png 좌상단 (0,0)-(560,330) 크롭 — 상단 벽까지 포함 |
| `data/seats.db` | 예약 DB (자동 생성, gitignore) |

## 초기화 방식

별도 크론 없음. 예약은 `day` 컬럼(KST 날짜)으로 저장되고, 화면을 그릴 때마다 `day < 오늘` 행을 삭제한다.
00:00이 지나면 첫 접속 시점에 전날 예약이 사라져 "23:59 초기화"와 동일하게 동작한다.

## GitHub Actions

`.github/workflows/ci.yml` — push마다 pytest(예약 충돌·1인1좌석·날짜 초기화·좌표 범위) 실행.
GitHub Actions는 상시 서버가 아니므로 실제 호스팅은 Streamlit Community Cloud(무료, 저장소 연결하면 끝)나 Docker로 한다.
Community Cloud는 컨테이너 재시작 시 SQLite가 지워지니 하루 단위 데이터인 이 앱에서는 문제 없다.
