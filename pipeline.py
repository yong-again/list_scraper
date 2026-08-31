"""팩션별 전체 파이프라인: 스크랩 → Excel 생성 → (대시보드 자동 반영).

army_list/{팩션}_army_list.xlsx 를 만들면 Streamlit 대시보드(app.py)가
폴더를 스캔해 자동으로 표시하므로, 이 스크립트만 돌리면 웹 반영까지 끝난다.

사용법:
    python pipeline.py --list                     # 사이트에서 지원하는 팩션 목록
    python pipeline.py "Ironjawz" "Sylvaneth"     # 지정한 팩션들 수집
    python pipeline.py --all                      # 전체 팩션 수집 (오래 걸림)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

from list_scraper import BASE_URL, TRANSLATION_DIR, faction_slug, scrape, write_excel

FACTION_CACHE = Path("factions_cache.json")
ARMY_LIST_DIR = Path("army_list")


def fetch_site_factions(refresh: bool = False) -> list[str]:
    """listhammer 팩션 필터에서 정확한 팩션명 목록을 가져온다 (파일 캐시)."""
    if FACTION_CACHE.exists() and not refresh:
        return json.loads(FACTION_CACHE.read_text())

    print("사이트에서 팩션 목록 가져오는 중...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        page.locator(".p-multiselect").first.click()
        page.wait_for_selector(".p-multiselect-option, .p-multiselect-item", timeout=10000)
        opts = page.locator(".p-multiselect-option, .p-multiselect-item")
        names = [opts.nth(i).inner_text().strip() for i in range(opts.count())]
        browser.close()

    FACTION_CACHE.write_text(json.dumps(names, ensure_ascii=False, indent=2))
    return names


def resolve_faction(name: str, site_factions: list[str]) -> str | None:
    """입력 팩션명을 사이트 표기와 대소문자 무시로 매칭 (예: 'lumineth realm-lords' → 'Lumineth Realm-Lords')."""
    by_lower = {f.lower(): f for f in site_factions}
    return by_lower.get(name.strip().lower())


def run_faction(faction: str, timeout_ms: int, retries: int = 1) -> bool:
    print(f"\n{'=' * 60}\n▶ {faction}\n{'=' * 60}")
    url = f"{BASE_URL}?faction={quote_plus(faction)}"
    df = scrape(url, headless=True, timeout_ms=timeout_ms, max_pages=None, faction=faction,
                retries=retries)
    if df.empty:
        print(f"⚠ {faction}: 수집된 리스트가 없습니다 (대회 데이터 없음 또는 팩션명 불일치).")
        return False

    xlsx = ARMY_LIST_DIR / f"{faction.replace(' ', '_')}_army_list.xlsx"
    write_excel(df, faction, xlsx)
    n_lists = df[["player", "event", "date"]].astype(str).agg("|".join, axis=1).nunique()
    print(f"✔ {faction}: 리스트 {n_lists}개 / 유닛 행 {len(df)}개 → {xlsx}")

    if not (TRANSLATION_DIR / f"{faction_slug(faction)}.ko.json").exists():
        print(f"  ℹ 번역 파일 없음 → 팩션 룰 시트는 영어 원문만 표시됩니다. "
              f"(translations/{faction_slug(faction)}.ko.json 생성 시 한국어 번역 추가)")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="listhammer 팩션별 스크랩 → Excel → 대시보드 파이프라인")
    ap.add_argument("factions", nargs="*", help="수집할 팩션명 (사이트 표기, 대소문자 무관)")
    ap.add_argument("--all", action="store_true", help="사이트의 전체 팩션 수집")
    ap.add_argument("--list", action="store_true", help="사용 가능한 팩션 목록 출력")
    ap.add_argument("--refresh-factions", action="store_true", help="팩션 목록 캐시 갱신")
    ap.add_argument("--timeout", type=int, default=15000, help="행별 대기 타임아웃 (ms)")
    ap.add_argument("--retries", type=int, default=1,
                    help="행별 로딩 타임아웃 시 재시도 횟수 (기본: 1번 재시도, 총 2번 시도)")
    ap.add_argument("--delay", type=int, default=5, help="팩션 간 대기 초 (사이트 부하 방지)")
    args = ap.parse_args()

    site_factions = fetch_site_factions(refresh=args.refresh_factions)

    if args.list:
        print("\n".join(site_factions))
        return

    if args.all:
        targets = site_factions
    elif args.factions:
        targets, unknown = [], []
        for name in args.factions:
            resolved = resolve_faction(name, site_factions)
            (targets if resolved else unknown).append(resolved or name)
        if unknown:
            print(f"알 수 없는 팩션: {unknown}\n사용 가능한 목록은 --list 로 확인하세요.", file=sys.stderr)
            sys.exit(1)
    else:
        ap.print_help()
        return

    ok, failed = [], []
    for i, faction in enumerate(targets):
        try:
            (ok if run_faction(faction, args.timeout, args.retries) else failed).append(faction)
        except Exception as exc:  # 한 팩션 실패가 전체를 멈추지 않게
            print(f"✖ {faction}: 오류 — {exc}", file=sys.stderr)
            failed.append(faction)
        if i < len(targets) - 1:
            time.sleep(args.delay)

    print(f"\n{'=' * 60}")
    print(f"완료: {len(ok)}개 성공" + (f", 실패/데이터 없음: {failed}" if failed else ""))
    print("대시보드 반영: 실행 중인 Streamlit을 새로고침하면 새 팩션이 목록에 나타납니다.")


if __name__ == "__main__":
    main()
