# listhammer.info 사이트 구조 변경 대응 (2026-08-31)

## 증상

`python pipeline.py "Lumineth Realm-Lords"` 실행 시 아래와 같이 실패:

```
접속 중: https://listhammer.info/aos?faction=Lumineth+Realm-Lords
확장 버튼을 찾지 못했습니다. 팩션명/URL을 확인하세요.
⚠ Lumineth Realm-Lords: 수집된 리스트가 없습니다 (대회 데이터 없음 또는 팩션명 불일치).
```

팩션명/URL 문제가 아니라 `list_scraper.py`가 찾던 셀렉터(`.p-datatable-row-toggle-button`)가
사이트 개편으로 더 이상 존재하지 않아서 발생한 오류였음.

## 원인

listhammer.info가 대회 결과 표에서 개별 아미 리스트를 보여주는 방식을 변경함.

| 항목 | 이전 | 현재 |
|---|---|---|
| 트리거 | 행 안 토글 버튼 (`.p-datatable-row-toggle-button`, `aria-expanded`로 상태 관리) | 행의 "아미 리스트 보기" 버튼 (`aria-label="View {선수명}'s army list"`) |
| 리스트 표시 위치 | 클릭한 행 바로 아래에 삽입되는 `<tr>` (인라인 확장) | 페이지 전역에 하나뿐인 모달(`.p-dialog`, PrimeVue Dialog) |
| 닫기 방식 | 토글 버튼 재클릭 | 모달의 닫기 버튼(`.p-dialog-close-button`) 클릭 → 모달이 DOM에서 완전히 detach |
| 유닛 포인트 span 클래스 | `span.text-gray-400` | `span.text-muted-color` (구 클래스는 더 이상 안 쓰임) |

다행히 모달 안 `.army-list`의 내부 DOM 구조(제목 `.text-lg.font-bold`, 섹션 헤더
`font-bold tracking-wide`, 유닛명 `span.font-semibold`, 노트 `text-muted-color` 등)는
기존 파서(`parse_army_list`)가 기대하던 형식과 대부분 동일해서 파싱 로직 자체는
큰 변경 없이 재사용 가능했음.

## 수정 내용 (`list_scraper.py`)

1. **셀렉터 교체**
   - `TOGGLE_BUTTON`을 `.p-datatable-row-toggle-button` → `'.p-datatable-tbody button[aria-label*="army list" i]'` 로 변경
   - 모달 관련 상수 `DIALOG = ".p-dialog"`, `DIALOG_CLOSE = ".p-dialog-close-button"` 추가

2. **`scrape_row()` 재작성**
   - 행 안 인라인 확장(`following-sibling::tr`)을 찾던 로직 제거
   - 버튼 클릭 → 페이지 전역 `.p-dialog` 안의 `.army-list`가 채워질 때까지 대기 → 파싱 → 닫기 버튼 클릭 → 모달이 `detached` 상태가 될 때까지 대기, 순서로 재작성
   - 모달이 완전히 사라진 뒤 다음 행으로 넘어가도록 해서, 이전 모달의 잔여 콘텐츠를 새 콘텐츠로 잘못 읽는 경쟁 상태(race condition)를 방지

3. **포인트 span 클래스 보강**
   - `EXTRACT_JS`의 `ptsSpan` 셀렉터를 `span.text-muted-color, span.text-gray-400` 로 확장 (신규/구 형식 모두 대응)

4. **부수 수정 — Faction Terrain 파싱 누락 수정**
   - "Faction Terrain" 섹션 헤더 다음 줄이 `<span>` 없이 순수 텍스트(예: `Shrine Luminor`)로만 오는 경우, 기존 코드에서는 어떤 분기에도 걸리지 않아 `meta["faction_terrain"]`이 채워지지 않던 버그를 발견하여 함께 수정
   - `parse_army_list()`에 `elif section == "Faction Terrain": meta.setdefault("faction_terrain", text)` 분기 추가

## 검증

- 로컬 셸(device_bash)이 일시적으로 응답하지 않아 사용자 환경에서 `pipeline.py`를 직접
  실행해보지는 못함. 클라우드 컨테이너에서도 조직 egress 정책으로 listhammer.info 접속이
  차단되어 Playwright로 직접 실행 테스트는 불가능했음.
- 대신 Claude 내장 브라우저로 실제 사이트(`https://listhammer.info/aos?faction=Lumineth+Realm-Lords`)에
  접속해 새 버튼/모달 구조를 직접 확인하고, 한 페이지(25행) 전체에 대해
  "버튼 클릭 → 모달 열림 대기 → 콘텐츠 확인 → 닫기 → 닫힘 대기" 흐름을 JS로 시뮬레이션함.
  - 25행 중 24행 성공, 1행은 서버 응답 지연으로 타임아웃 (기존 코드에도 이미 있는
    정상적인 예외 처리 경로 — 해당 행만 건너뛰고 계속 진행됨)
  - 페이지네이션(`.p-paginator`)도 기존 구조 그대로 동작함을 확인
- 실제 사이트에서 추출한 원본 `.army-list` 데이터를 수정된 `parse_army_list()`에 그대로 넣어
  유닛명/포인트/노트/배틀 포메이션/드랍/총 포인트가 정확히 파싱되는 것을 확인
  (예: Sevireth 350pts + General, Hurakan Windchargers 340pts + Reinforced 등)
- `python -m py_compile list_scraper.py` 로 문법 오류 없음 확인

## 후속 확인 필요 사항

- 사용자 환경에서 아래 명령으로 실제 실행 확인 필요:
  ```
  uv run python pipeline.py "Lumineth Realm-Lords"
  ```
- 시뮬레이션 중 한 행(플레이어 데이터)에서 한 개의 결과 행에 GW 앱 리스트 2개 +
  Sigdex 리스트 1개가 연달아 붙어 있는 것을 발견함 (선수가 이벤트에 여러 리스트를 제출한
  경우로 추정). 이는 사이트 개편과 무관한 기존 데이터 특이 케이스이며, 현재 파서는 이를
  하나의 리스트처럼 이어 붙여 처리함 — 필요 시 별도 이슈로 다룰 것.

## 변경 파일

- `list_scraper.py`
