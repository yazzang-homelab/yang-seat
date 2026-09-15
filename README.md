# yang-seat — 오피스 자리 선점

Streamlit 앱. 로그인 → 도면 위 원을 클릭해 그날 자리를 선점. 관리자가 별칭을 주면 화면에 ID 대신 별칭이 보인다. 1인 1좌석, 매일 23:59(KST) 초기화, 10초마다 자동 갱신.
관리자 페이지(`/?page=admin`)에서 접속 허용 계정을 등록·삭제한다. PW는 관리자가 정하지 않는다 — 등록된 사용자가 **처음 접속할 때 숫자 4자리를 직접 설정**하고, 잊으면 관리자가 초기화해 다시 설정하게 한다.

## 배포 (Streamlit Community Cloud — 외부 호스팅, LTE 접속용)

1. 이 저장소를 GitHub에 올린다 (이미: `yazzang-homelab/yang-seat`, public — Community Cloud 무료 플랜은 public 저장소만).
2. https://share.streamlit.io → **New app** → 저장소·브랜치 `master`·파일 `app.py` 선택.
3. **Advanced settings → Secrets** 에 아래를 넣는다 (영속화 — 없으면 재배포 때 추가한 계정이 사라진다):
   ```toml
   GIST_ID = "<secret gist id>"          # 저장소가 public이므로 README에 적지 않는다 — gist에 계정·비번이 평문으로 들어간다
   GITHUB_TOKEN = "<gist 권한만 있는 GitHub PAT>"
   ```
4. Deploy. URL은 `https://<앱이름>.streamlit.app`.

GitHub Actions(`.github/workflows/ci.yml`)는 push마다 pytest만 돈다 — Actions는 상시 서버가 아니므로 호스팅은 Streamlit Cloud가 한다.

## 사용

| 화면 | 주소 | 설명 |
|---|---|---|
| 자리 선점 | `/` | 초록 원 클릭=선점, 파란 원(내 자리) 클릭=취소, 회색=다른 사람 |
| 관리자 | `/?page=admin` | 초기 계정 `yang / 1234`. 계정 등록(ID·별칭·관리자 여부)·**CSV 일괄 등록/내려받기**(A열 ID, B열 별칭)·**PW 초기화**·삭제, 오늘 예약 강제 해제 |

관리자가 아닌 계정으로 `/?page=admin`에 들어가면 "권한 없음"만 뜬다.

## 파일

| 파일 | 역할 |
|---|---|
| `app.py` | 앱 전체 (로그인·클릭형 좌석 맵·선점/취소·관리자·SQLite) |
| `store.py` | GitHub Gist 미러 — 계정과 오늘 예약 스냅샷을 저장/복원 |
| `seatmap/index.html` | 커스텀 컴포넌트 — 도면 위 원을 클릭하면 선점/취소 |
| `seats.json` | 좌석 45개 (3.png 색 박스에서 추출: LSS 13 · SCC 14 · CSO 17 · CGM 1). id/zone 편집 가능 |
| `users.json` | 최초 시드 계정 (gist가 비어 있을 때 1회만 사용) |
| `floor.png` | 3.png (40,30)-(880,500) 크롭 |

## 동작 원리

- **동시성**: 프로세스 내 단일 SQLite 연결(WAL) + `PRIMARY KEY(day, seat)` / `UNIQUE(day, user)`. 두 사람이 같은 자리를 동시에 눌러도 DB가 한 명만 받고 나머지는 "이미 ○○님이 선점" 메시지.
- **초기화**: 예약은 KST 날짜 키로 저장되고 날짜가 바뀐 뒤 첫 요청에서 이전 날짜 행을 삭제 — 크론 불필요.
- **영속화**: Streamlit Cloud는 재시작 시 디스크가 초기화되므로 변경 직후 gist에 스냅샷을 쓰고 기동 시 복원한다. 시크릿이 없으면 로컬 전용(개발 모드)이며 관리자 페이지에 경고가 뜬다.

## 로컬 실행

```bash
pip install -r requirements.txt
streamlit run app.py          # http://localhost:8501
pytest -q                     # 4 tests
```
