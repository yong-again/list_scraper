# Listhammer 메타 분석 파이프라인

listhammer.info의 AoS 대회 아미 리스트를 수집해 Excel 리포트와 웹 대시보드로 만드는 도구.

## 전체 흐름

```
pipeline.py (스크랩 + Excel 생성)  →  army_list/*.xlsx  →  app.py (웹 대시보드)  →  share.sh (외부 공유)
```

## 설치

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium    # 크롤러용 브라우저 (별도 다운로드)
```

## 사용법

### 0. 포인트 패치 반영 (새 Battle Profiles PDF가 나왔을 때)

```bash
# battleprofiles/ 에 새 PDF를 넣고:
.venv/bin/python update_points.py --dry-run    # 변경점 미리보기
.venv/bin/python update_points.py             # warscolls/*.json 포인트 갱신
```

변경된 유닛에는 `points_prev`(이전 값)와 `points_updated`(패치 기준일, 예: 2026-06)가 기록된다.
갱신 후 Excel 리포트를 재생성해야 통계에 반영된다.

### 1. 팩션 수집 (스크랩 → Excel)

```bash
.venv/bin/python pipeline.py --list                     # 지원 팩션 목록 (25개)
.venv/bin/python pipeline.py "Ironjawz" "Sylvaneth"     # 지정 팩션 수집 (대소문자 무관)
.venv/bin/python pipeline.py --all                      # 전체 팩션 (약 1시간)
```

팩션당 `army_list/{팩션}_army_list.xlsx` 생성 — 3개 시트:
- **아미 리스트**: 유닛별 원본 데이터
- **팩션 룰(번역)**: wahapedia 룰 원문 + 한국어 번역 (`translations/{slug}.ko.json` 있을 때)
- **통계 분석**: 포메이션/유닛/강화/장군 통계

### 1-1. 주간 자동 갱신

수집 대상 팩션은 `config.json` 에서 관리한다 (한 개든 여러 개든 동일).

```jsonc
{
  "factions": ["Ironjawz", "Kharadron Overlords"],  // "Ironjawz" 처럼 한 개만 써도 되고, "all" 이면 전체 팩션
  "timeout_ms": 15000,      // 행별 대기 타임아웃
  "delay_sec": 5,           // 팩션 간 대기 (사이트 부하 방지)
  "keep_backups": 4,        // army_list/history/ 에 보관할 이전 xlsx 개수
  "schedule": { "weekday": "sun", "hour": 4, "minute": 0 }
}
```

```bash
.venv/bin/python weekly_update.py --list       # 설정된 대상 확인
.venv/bin/python weekly_update.py --run        # 지금 한 번 실행
.venv/bin/python weekly_update.py --run --faction Ironjawz   # config 무시하고 지정 팩션만
.venv/bin/python weekly_update.py --install    # 매주 자동 실행 등록 (macOS launchd)
.venv/bin/python weekly_update.py --status     # 등록 상태 / 최근 실행 결과
.venv/bin/python weekly_update.py --uninstall  # 자동 실행 해제
```

- 갱신 전 기존 xlsx는 `army_list/history/{팩션}_YYYYMMDD.xlsx` 로 백업 (최근 `keep_backups`개 유지).
- 실행 로그는 `logs/update_*.log` (최근 12주치), 마지막 결과 요약은 `update_state.json`.
- 한 팩션이 실패해도 나머지는 계속 진행하며, 실패 목록이 상태/로그에 남는다.
- `--install` 은 `config.json` 의 `schedule` 을 읽어 plist를 만든다. 스케줄을 바꾸면 `--install` 을 다시 실행할 것.
- 예약 시각에 맥이 꺼져 있거나 잠들어 있으면 launchd가 깨어난 직후에 실행한다.

### 2. 웹 대시보드

```bash
.venv/bin/streamlit run app.py
```

`army_list/` 폴더를 자동 스캔하므로 터미널에서 새 팩션을 수집하면 브라우저 새로고침만 하면 된다.

사이드바의 **"➕ 새 팩션 수집"** 에서는 터미널 없이도 바로 수집할 수 있다: 검색창에 입력하거나
목록을 펼쳐 클릭해 팩션을 하나 이상 고른 뒤 "스크랩 시작"을 누르면 되고, 진행 상황이 실시간으로
표시되며 끝나면 방금 수집한 팩션이 자동으로 선택된다. (이미 수집된 팩션은 ✅ 로 표시되며, 다시
선택하면 최신 데이터로 갱신된다.)

### 3. 외부 공유 (Cloudflare 터널)

```bash
./share.sh    # 포그라운드 공유 (Ctrl+C로 종료, 창을 닫으면 끊김)
```

터미널을 닫아도 계속 공유하려면 백그라운드 스크립트를 쓴다.

```bash
./share_bg.sh start     # 대시보드 + 터널을 백그라운드로 띄우고 공유 주소 출력
./share_bg.sh status    # 실행 상태와 현재 주소
./share_bg.sh url       # 주소만 출력 (복사용)
./share_bg.sh logs      # 로그 실시간 보기 (Ctrl+C로 나가도 계속 실행됨)
./share_bg.sh restart   # 재시작 (주소 새로 발급)
./share_bg.sh stop      # 종료
```

주소는 시작할 때마다 바뀐다. PID는 `run/`, 로그는 `logs/share_*.log` 에 남는다.
포트는 기본 8765이며 `PORT=9000 ./share_bg.sh start` 로 바꿀 수 있다.

## 파일 구성

| 경로 | 설명 |
|---|---|
| `list_scraper.py` | 크롤러 본체 + Excel 생성 + 통계 로직 (단일 팩션 실행도 가능) |
| `pipeline.py` | 다중 팩션 일괄 파이프라인 |
| `weekly_update.py` | 주간 자동 갱신 (config 기반 실행 + launchd 등록/해제) |
| `config.json` | 갱신 대상 팩션·스케줄·백업 설정 |
| `app.py` | Streamlit 대시보드 |
| `share.sh` | Cloudflare 퀵 터널 공유 (포그라운드) |
| `share_bg.sh` | 공유 백그라운드 실행 (start/stop/status/url/logs) |
| `wahapedia_factions/` | 팩션 룰 원문 (JSON) |
| `warscolls/` | 워스크롤 (유닛 역할 분류에 keywords 사용) |
| `translations/` | 팩션 룰 한국어 번역 (`{slug}.ko.json`, 수동 작성) |
| `factions_cache.json` | 사이트 팩션명 캐시 (`--refresh-factions`로 갱신) |

## 참고

- 리스트 형식이 빌더별로 6가지 이상이라 파서가 형식별 분기 처리함. 새 팩션에서
  통계에 "(불명)"/"기타"가 많이 보이면 해당 리스트의 `.army-list` HTML을 확인할 것.
- 번역 파일이 없는 팩션은 룰 시트에 영어 원문만 표시됨 (파이프라인이 알려줌).
- 배틀 포메이션은 wahapedia의 "Battle Formations > X" 섹션명 화이트리스트로 검증.
