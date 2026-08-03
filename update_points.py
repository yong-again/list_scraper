"""Battle Profiles PDF와 warscolls/*.json의 유닛 포인트 비교·갱신.

PDF에서 팩션별 유닛 포인트를 읽어 warscroll JSON과 다르면 JSON을 수정하고,
points_prev(이전 값)와 points_updated(패치 기준일)를 기록한다. 멱등적으로 동작
(이미 갱신된 항목은 건너뜀).

사용법:
    python update_points.py [battleprofiles/xxx.pdf]   # 생략 시 폴더의 첫 PDF
    python update_points.py --dry-run                  # 변경 없이 비교 결과만
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

WARSCROLL_DIR = Path("warscolls")
PROFILE_DIR = Path("battleprofiles")

MONTHS = {m: i for i, m in enumerate(
    ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
     "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"], 1)}


def norm(s: str) -> str:
    """느슨한 이름 비교용: 영숫자만 남기고 소문자화 (PDF의 임의 공백/하이픈 무시)."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pdf_date_label(first_page_text: str) -> str:
    m = re.search(r"(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{4})",
                  first_page_text.upper())
    return f"{m.group(2)}-{MONTHS[m.group(1)]:02d}" if m else "unknown"


def faction_page_ranges(reader: PdfReader) -> dict[str, tuple[int, int]]:
    """목차에서 팩션별 (시작, 끝) PDF 페이지 인덱스 범위 추출."""
    contents = reader.pages[1].extract_text()
    entries = []
    for line_name, page_no in re.findall(r"([A-Z][A-Za-z'’ \-]+?)\s*(?:[.\s]{3,}| +)\s*(\d+)", contents):
        name = line_name.strip()
        if name.upper() in ("ORDER", "CHAOS", "DEATH", "DESTRUCTION", "CONTENTS"):
            continue
        entries.append((name, int(page_no)))
    entries.sort(key=lambda e: e[1])
    ranges = {}
    for i, (name, start) in enumerate(entries):
        end = entries[i + 1][1] - 1 if i + 1 < len(entries) else len(reader.pages)
        ranges[norm(name)] = (start - 1, end)  # 인쇄 페이지 N = PDF 인덱스 N-1
    return ranges


# 행 시작 마커: 앞에 다른 유닛명이 붙어 있으면 부분 문자열 오탐
# (예: "Abhorrant Ghoul King on Royal Terrorgheist 400"에 "Royal Terrorgheist"가 매칭되는 것 방지)
LINE_MARKERS = re.compile(r"^[\s✹•*]*(?:NEW|UPDATED|LEGENDS)?[\s✹•*]*$", re.IGNORECASE)


def name_pattern(unit_name: str) -> str:
    tokens = re.findall(r"\w+", unit_name)
    return r"\W{0,3}".join(re.escape(t) for t in tokens)


def clean_line_prefix(text: str, start: int) -> bool:
    """매칭 시작 위치의 같은 줄 앞부분이 마커뿐인지(=행의 시작인지) 확인."""
    line_start = text.rfind("\n", 0, start) + 1
    return bool(LINE_MARKERS.match(text[line_start:start]))


def find_unit_points(unit_name: str, unit_size, keywords: list[str], text: str,
                     claimed: list[tuple[tuple[int, int], str]]) -> tuple[int, tuple[int, int]] | None:
    """'유닛명 <유닛수> <포인트>' 행을 찾는다. 검증: 행 시작 + 유닛수 일치 + 미선점 구간.

    FACTION TERRAIN은 'Faction Terrain <이름> <포인트>' 단일 숫자 형식.
    같은 이름의 중복 warscroll 항목은 같은 행을 공유할 수 있다.
    """
    if "FACTION TERRAIN" in keywords:
        m = re.search(r"Faction\W+Terrain\W+" + name_pattern(unit_name) + r"\W+(\d+)",
                      text, re.IGNORECASE)
        return (int(m.group(1)), m.span()) if m else None

    me = norm(unit_name)
    pattern = name_pattern(unit_name) + r"\W+(\d+)\s+(\d+)(?:\s*\(\s*[+-]\s*\d+\s*\))?"
    for m in re.finditer(pattern, text, re.IGNORECASE):
        if any(s < m.end() and m.start() < e and owner != me for (s, e), owner in claimed):
            continue  # 다른(더 긴) 이름의 유닛이 이미 차지한 행
        if not clean_line_prefix(text, m.start()):
            continue  # 다른 이름/텍스트 뒤에 붙은 부분 매칭
        if unit_size and int(m.group(1)) != int(unit_size):
            continue  # 유닛 규모 불일치 (연대 옵션 등 다른 문맥의 숫자)
        return int(m.group(2)), m.span()
    return None


def process_faction(path: Path, text: str, date_label: str, dry_run: bool) -> dict:
    units = json.loads(path.read_text())
    changed, missing = [], []
    claimed: list[tuple[tuple[int, int], str]] = []
    # 긴 이름부터 처리해 짧은 이름이 긴 이름의 일부에 매칭되는 것을 방지
    for u in sorted(units, key=lambda x: -len(x["name"])):
        found = find_unit_points(u["name"], u.get("unit_size"), u.get("keywords", []),
                                 text, claimed)
        if found is None:
            missing.append(u["name"])
            continue
        new_points, span = found
        claimed.append((span, norm(u["name"])))
        old_points = u.get("points")
        if old_points != new_points:
            changed.append((u["name"], old_points, new_points))
            u["points_prev"] = old_points
            u["points"] = new_points
            u["points_updated"] = date_label
    if changed and not dry_run:
        path.write_text(json.dumps(units, ensure_ascii=False, indent=1) + "\n")
    return {"changed": changed, "missing": missing, "total": len(units)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Battle Profiles PDF → warscolls 포인트 갱신")
    ap.add_argument("pdf", nargs="?", help="Battle Profiles PDF 경로 (생략 시 battleprofiles/ 첫 PDF)")
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 비교 결과만 출력")
    args = ap.parse_args()

    pdf_path = Path(args.pdf) if args.pdf else next(PROFILE_DIR.glob("*.pdf"), None)
    if not pdf_path or not pdf_path.exists():
        print("PDF를 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    reader = PdfReader(str(pdf_path))
    date_label = pdf_date_label(reader.pages[0].extract_text())
    print(f"PDF: {pdf_path.name}\n기준일: {date_label} (Battle Profiles)\n")

    ranges = faction_page_ranges(reader)
    page_texts = [p.extract_text() for p in reader.pages]

    total_changed = 0
    for path in sorted(WARSCROLL_DIR.glob("*.json")):
        units = json.loads(path.read_text())
        if not units:
            continue
        faction = units[0].get("faction", path.stem)
        rng = ranges.get(norm(faction))
        if rng is None:
            print(f"— {faction}: PDF 목차에 없음 (구판 팩션?) — 건너뜀")
            continue
        text = "\n".join(page_texts[rng[0]:rng[1]])
        r = process_faction(path, text, date_label, args.dry_run)
        total_changed += len(r["changed"])
        status = f"{faction}: 변경 {len(r['changed'])}건 / 전체 {r['total']}개 유닛"
        if r["missing"]:
            status += f" / PDF에서 못 찾음 {len(r['missing'])}개"
        print(("[dry-run] " if args.dry_run else "") + status)
        for name, old, new in r["changed"]:
            print(f"    {name}: {old} → {new}")
        if r["missing"]:
            print(f"    (못 찾음: {', '.join(r['missing'][:6])}{' ...' if len(r['missing']) > 6 else ''})")

    print(f"\n총 {total_changed}건 포인트 갱신" + (" (dry-run: 실제 파일 미변경)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
