# 행별 로딩 타임아웃 재시도 로직 추가 (2026-08-31)

## 증상

원격 SSH 서버에서 `pipeline.py "Lumineth Realm-Lords"` 실행 중 대회 리스트 행의 절반 가량이
"상세 내용 로딩 시간 초과 — 건너뜀" 으로 스킵됨. 모달(.p-dialog) 안 `.army-list` 콘텐츠를 행마다
서버에서 별도로 불러오는데, 이 응답이 느릴 때 기존 15초 타임아웃 안에 못 들어오면 그 행을 통째로
건너뛰는 구조였음 (8/31 오전 사이트 구조 변경 대응 때 브라우저로 직접 확인했을 때도 25행 중 1행은
이런 식으로 타임아웃되는 걸 관찰한 바 있음 — 네트워크 상태에 따라 빈도가 더 높아질 수 있음).

## 원인

`scrape_row()`가 모달 콘텐츠 로딩을 한 번만 기다리고, 실패하면 바로 포기하는 구조였음. 재시도가
없어서 일시적인 서버 응답 지연에도 데이터가 통째로 유실됨.

## 수정 내용

### `list_scraper.py`

- `scrape_row()`에 `retries: int = 1` 파라미터 추가. 타임아웃이 나면:
  1. 열린 채로 멈춰 있을 수 있는 모달을 정리 (닫기 버튼 클릭 + detach 대기, 실패해도 무시)
  2. `retries`번 더 재시도
  3. 마지막 시도까지 실패하면 기존과 동일하게 `PlaywrightTimeoutError`를 그대로 올려서
     호출부(`scrape()`)가 해당 행을 건너뛰고 계속 진행하도록 함 (기존 동작 유지)
- `scrape()`에도 `retries: int = 1` 파라미터를 추가해 `scrape_row()`로 그대로 전달
- CLI에 `--retries` 옵션 추가 (기본값 1 = 총 2번 시도)

### `pipeline.py`

- `run_faction(faction, timeout_ms, retries=1)` — `scrape()`로 전달
- CLI에 `--retries` 옵션 추가, `main()`에서 `run_faction()` 호출 시 전달

### `weekly_update.py`

- `config.json` 로딩 시 기본값에 `"retries": 1` 추가
- `run_faction()` 호출 시 `cfg["retries"]` 전달

### `app.py`

- `default_retries()` 헬퍼 추가 (`config.json`의 `retries` 읽기, 기본 1)
- 대시보드의 "새 팩션 수집" 스크랩 실행 시 `run_faction(fac, timeout_ms, retries)`로 전달

### `config.json`

- 이번 증상(절반 타임아웃)에 대응해 사용자 설정값을 상향:
  `"timeout_ms": 15000 → 20000`, `"retries": 2` 추가 (총 3번 시도)
- `weekly_update.py`/대시보드에서 이 설정을 그대로 씀

### `README.md`

- `pipeline.py` 사용 예시에 `--timeout`/`--retries` 조합 예시 추가
- `config.json` 필드 설명에 `retries` 추가

## 검증

- 셸(device_bash)이 계속 응답하지 않아 사용자 컴퓨터·SSH 서버 어느 쪽에서도 직접 실행 확인은
  못 함. 클라우드 컨테이너는 listhammer.info 접속이 조직 egress 정책으로 막혀 있어 실사이트
  테스트도 불가능.
- 대신 로컬 HTML 픽스처(`file://`)로 재시도 로직만 독립적으로 검증:
  - **회복 케이스**: 첫 클릭은 3초 뒤에야 모달이 뜨도록(타임아웃 1초로 설정), 재시도(2번째 클릭)는
    바로 뜨도록 만든 픽스처로 `scrape_row(timeout_ms=1000, retries=1)` 호출 → 1차 타임아웃 →
    자동 정리 → 재시도 → 성공적으로 파싱된 결과(`Test Unit`, 300pt) 확인
  - **소진 케이스**: 항상 10초 뒤에만 모달이 뜨는 픽스처로 `retries=1` 호출 → 두 번 모두 시도한 뒤
    (매 시도 사이 모달 정리까지 마치고) `PlaywrightTimeoutError`가 정상적으로 올라오는 것 확인 —
    호출부의 기존 "건너뛰기" 처리가 그대로 동작함을 의미
- 모든 수정 파일 `py_compile` 통과, `config.json` JSON 유효성 확인

## 사용자 조치 필요

이번 수정은 사용자 컴퓨터(list_scraper 프로젝트)에만 반영했다. **SSH 서버는 별도 환경이라
자동으로 반영되지 않으므로**, 그 서버가 이 저장소를 git으로 관리한다면 `git pull` (또는 동일한
방식으로 커밋 후 서버에서 pull), 아니면 수정된 5개 파일(`list_scraper.py`, `pipeline.py`,
`weekly_update.py`, `app.py`, `config.json`)을 직접 복사해 반영해야 한다.

## 변경 파일

- `list_scraper.py`, `pipeline.py`, `weekly_update.py`, `app.py`, `config.json`, `README.md`
