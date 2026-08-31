"""주 1회 자동 갱신: config.json의 팩션을 스크랩해 army_list/*.xlsx를 새로 만든다.

config.json 의 `factions` 로 대상 팩션을 관리한다 (한 개든 여러 개든 동일하게 동작).

    "factions": "Ironjawz"                      # 한 개
    "factions": ["Ironjawz", "Sylvaneth"]       # 여러 개
    "factions": "all"                           # 사이트 전체 팩션

사용법:
    python weekly_update.py --run                    # 지금 한 번 실행 (config 대상 전체)
    python weekly_update.py --run --faction Ironjawz # config 무시하고 지정 팩션만
    python weekly_update.py --list                   # 설정된 대상 확인
    python weekly_update.py --install                # 매주 자동 실행 등록 (launchd)
    python weekly_update.py --status                 # 등록 상태 / 최근 실행 결과
    python weekly_update.py --uninstall              # 자동 실행 해제
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from pipeline import ARMY_LIST_DIR, fetch_site_factions, resolve_faction, run_faction

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "update_state.json"
LOG_DIR = ROOT / "logs"
BACKUP_DIR = ARMY_LIST_DIR / "history"

LABEL = "info.listhammer.list-scraper.weekly"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

DEFAULTS = {
    "factions": [],
    "timeout_ms": 15000,
    "retries": 1,
    "delay_sec": 5,
    "keep_backups": 4,
    "schedule": {"weekday": "sun", "hour": 4, "minute": 0},
}


# --------------------------------------------------------------------------- config

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"설정 파일이 없습니다: {CONFIG_PATH}")
    cfg = DEFAULTS | json.loads(CONFIG_PATH.read_text())
    cfg["schedule"] = DEFAULTS["schedule"] | cfg.get("schedule", {})
    return cfg


def config_targets(cfg: dict, overrides: list[str] | None = None) -> list[str]:
    """config(또는 --faction 인자)의 팩션명을 사이트 표기로 정규화한다."""
    raw = overrides if overrides else cfg["factions"]
    if isinstance(raw, str):
        raw = [raw]  # 팩션 한 개는 문자열로도 적을 수 있게
    if not raw:
        sys.exit("대상 팩션이 없습니다. config.json 의 factions 를 채워주세요.")

    site = fetch_site_factions()
    if len(raw) == 1 and str(raw[0]).strip().lower() == "all":
        return site

    targets, unknown = [], []
    for name in raw:
        resolved = resolve_faction(str(name), site)
        (targets if resolved else unknown).append(resolved or name)
    if unknown:
        sys.exit(f"알 수 없는 팩션: {unknown}\n사용 가능한 목록: python pipeline.py --list")
    return targets


# --------------------------------------------------------------------------- 실행

def log(msg: str, fh) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def backup_existing(faction: str, keep: int) -> None:
    """직전 xlsx를 army_list/history/ 로 보관하고 오래된 것부터 정리한다."""
    src = ARMY_LIST_DIR / f"{faction.replace(' ', '_')}_army_list.xlsx"
    if not src.exists() or keep <= 0:
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    shutil.copy2(src, BACKUP_DIR / f"{stem}_{datetime.now():%Y%m%d}.xlsx")
    old = sorted(BACKUP_DIR.glob(f"{stem}_*.xlsx"))
    for path in old[:-keep]:
        path.unlink()


def run(cfg: dict, targets: list[str]) -> int:
    LOG_DIR.mkdir(exist_ok=True)
    ARMY_LIST_DIR.mkdir(exist_ok=True)
    started = datetime.now()
    log_path = LOG_DIR / f"update_{started:%Y%m%d_%H%M%S}.log"

    ok, failed = [], []
    with log_path.open("w") as fh:
        log(f"주간 갱신 시작 — 대상 {len(targets)}개: {', '.join(targets)}", fh)
        for i, faction in enumerate(targets):
            try:
                backup_existing(faction, cfg["keep_backups"])
                success = run_faction(faction, cfg["timeout_ms"], cfg["retries"])
                (ok if success else failed).append(faction)
                log(f"{'✔' if success else '⚠'} {faction}", fh)
            except Exception as exc:  # 한 팩션 실패가 전체를 멈추지 않게
                failed.append(faction)
                log(f"✖ {faction}: {exc}", fh)
            if i < len(targets) - 1:
                time.sleep(cfg["delay_sec"])
        log(f"완료 — 성공 {len(ok)}개" + (f", 실패 {failed}" if failed else ""), fh)

    STATE_PATH.write_text(json.dumps({
        "last_run": started.isoformat(timespec="seconds"),
        "duration_sec": round((datetime.now() - started).total_seconds()),
        "succeeded": ok,
        "failed": failed,
        "log": str(log_path.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))

    # 로그는 최근 12주치만 유지
    for path in sorted(LOG_DIR.glob("update_*.log"))[:-12]:
        path.unlink()

    return 0 if not failed else 1


# --------------------------------------------------------------------------- 스케줄 등록

def python_bin() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv if venv.exists() else Path(sys.executable))


def install(cfg: dict) -> None:
    sched = cfg["schedule"]
    weekday = sched["weekday"]
    if isinstance(weekday, str):
        if weekday.lower()[:3] not in WEEKDAYS:
            sys.exit(f"schedule.weekday 값이 잘못됐습니다: {weekday} (sun~sat 또는 0~6)")
        weekday = WEEKDAYS[weekday.lower()[:3]]

    LOG_DIR.mkdir(exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [python_bin(), str(ROOT / "weekly_update.py"), "--run"],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": {
            "Weekday": int(weekday),
            "Hour": int(sched["hour"]),
            "Minute": int(sched["minute"]),
        },
        "RunAtLoad": False,
        "StandardOutPath": str(LOG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.err.log"),
    }
    PLIST_PATH.write_bytes(plistlib.dumps(plist))

    subprocess.run(["launchctl", "bootout", f"gui/{os_uid()}/{LABEL}"],
                   capture_output=True)  # 기존 등록 제거 (없으면 무시)
    res = subprocess.run(["launchctl", "bootstrap", f"gui/{os_uid()}", str(PLIST_PATH)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"launchctl 등록 실패: {res.stderr.strip()}")

    day_ko = "일월화수목금토"[int(weekday)]
    print(f"✔ 매주 {day_ko}요일 {sched['hour']:02d}:{sched['minute']:02d} 자동 실행 등록 완료")
    print(f"  plist: {PLIST_PATH}")


def uninstall() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os_uid()}/{LABEL}"], capture_output=True)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("✔ 자동 실행 해제 완료")


def os_uid() -> int:
    return os.getuid()


def status(cfg: dict) -> None:
    res = subprocess.run(["launchctl", "print", f"gui/{os_uid()}/{LABEL}"],
                         capture_output=True, text=True)
    registered = res.returncode == 0
    sched = cfg["schedule"]
    print(f"스케줄 등록: {'예' if registered else '아니오'}"
          + (f" (매주 {sched['weekday']} {sched['hour']:02d}:{sched['minute']:02d})" if registered else ""))
    if STATE_PATH.exists():
        st = json.loads(STATE_PATH.read_text())
        print(f"최근 실행: {st['last_run']} ({st['duration_sec']}초)")
        print(f"  성공: {', '.join(st['succeeded']) or '없음'}")
        if st["failed"]:
            print(f"  실패: {', '.join(st['failed'])}")
        print(f"  로그: {st['log']}")
    else:
        print("최근 실행 기록 없음")


# --------------------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="listhammer 주간 자동 갱신")
    ap.add_argument("--run", action="store_true", help="지금 한 번 실행")
    ap.add_argument("--faction", action="append", metavar="NAME",
                    help="config 대신 이 팩션만 실행 (여러 번 지정 가능)")
    ap.add_argument("--list", action="store_true", help="설정된 대상 팩션 출력")
    ap.add_argument("--install", action="store_true", help="매주 자동 실행 등록")
    ap.add_argument("--uninstall", action="store_true", help="자동 실행 해제")
    ap.add_argument("--status", action="store_true", help="등록 상태와 최근 실행 결과")
    args = ap.parse_args()

    os.chdir(ROOT)  # pipeline/list_scraper 가 상대 경로를 쓰므로 항상 프로젝트 루트에서 동작

    if args.uninstall:
        uninstall()
        return

    cfg = load_config()

    if args.install:
        install(cfg)
    elif args.status:
        status(cfg)
    elif args.list:
        print("\n".join(config_targets(cfg, args.faction)))
    elif args.run:
        sys.exit(run(cfg, config_targets(cfg, args.faction)))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
