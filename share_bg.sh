#!/bin/bash
# Streamlit 대시보드 + Cloudflare 퀵 터널을 백그라운드로 실행 (터미널을 닫아도 유지됨)
#
#   ./share_bg.sh start     시작하고 공유 주소 출력
#   ./share_bg.sh status    실행 상태와 현재 주소
#   ./share_bg.sh url       공유 주소만 출력 (복사용)
#   ./share_bg.sh logs      로그 실시간 보기 (Ctrl+C로 빠져나와도 계속 실행됨)
#   ./share_bg.sh stop      앱과 터널 종료
#   ./share_bg.sh restart   재시작 (주소가 새로 발급됨)

set -euo pipefail
cd "$(dirname "$0")"

PORT=${PORT:-8765}
RUN_DIR=run
LOG_DIR=logs
APP_LOG="$LOG_DIR/share_streamlit.log"
TUNNEL_LOG="$LOG_DIR/share_tunnel.log"
APP_PID="$RUN_DIR/streamlit.pid"
TUNNEL_PID="$RUN_DIR/tunnel.pid"
URL_FILE="$RUN_DIR/share_url.txt"

mkdir -p "$RUN_DIR" "$LOG_DIR"

# $1 = pid 파일 → 해당 프로세스가 살아있으면 0
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

stop_one() {  # $1 = pid 파일, $2 = 표시 이름
    if alive "$1"; then
        kill "$(cat "$1")" 2>/dev/null || true
        for _ in $(seq 10); do alive "$1" || break; sleep 0.3; done
        alive "$1" && kill -9 "$(cat "$1")" 2>/dev/null || true
        echo "  중지: $2"
    fi
    rm -f "$1"
}

start() {
    if alive "$APP_PID" && alive "$TUNNEL_PID"; then
        echo "이미 실행 중입니다. 주소: $(cat "$URL_FILE" 2>/dev/null || echo '확인 중')"
        echo "(새 주소가 필요하면 ./share_bg.sh restart)"
        return 0
    fi
    command -v cloudflared >/dev/null || { echo "cloudflared 가 없습니다: brew install cloudflared" >&2; exit 1; }
    stop_one "$APP_PID" streamlit
    stop_one "$TUNNEL_PID" tunnel
    rm -f "$URL_FILE"

    echo "Streamlit 시작 (port $PORT)..."
    nohup .venv/bin/streamlit run app.py \
        --server.headless true --server.port "$PORT" >"$APP_LOG" 2>&1 &
    echo $! >"$APP_PID"

    for _ in $(seq 60); do
        curl -sf -o /dev/null "http://localhost:$PORT" && break
        alive "$APP_PID" || { echo "Streamlit 시작 실패 — $APP_LOG 확인" >&2; exit 1; }
        sleep 1
    done
    curl -sf -o /dev/null "http://localhost:$PORT" || { echo "Streamlit 응답 없음 — $APP_LOG 확인" >&2; exit 1; }

    echo "Cloudflare 터널 시작..."
    : >"$TUNNEL_LOG"
    nohup cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate >"$TUNNEL_LOG" 2>&1 &
    echo $! >"$TUNNEL_PID"

    # 터널 로그에 발급 주소가 찍힐 때까지 대기
    local url=""
    for _ in $(seq 60); do
        url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)
        [ -n "$url" ] && break
        alive "$TUNNEL_PID" || { echo "터널 시작 실패 — $TUNNEL_LOG 확인" >&2; stop; exit 1; }
        sleep 1
    done
    [ -n "$url" ] || { echo "주소 발급 실패 — $TUNNEL_LOG 확인" >&2; stop; exit 1; }

    echo "$url" >"$URL_FILE"
    echo ""
    echo "  공유 주소: $url"
    echo "  (주소는 시작할 때마다 바뀝니다. 중지: ./share_bg.sh stop)"
}

stop() {
    echo "종료 중..."
    stop_one "$TUNNEL_PID" "Cloudflare 터널"
    stop_one "$APP_PID" "Streamlit"
    rm -f "$URL_FILE"
    echo "완료"
}

status() {
    alive "$APP_PID"    && echo "Streamlit: 실행 중 (pid $(cat "$APP_PID"), port $PORT)" || echo "Streamlit: 중지됨"
    alive "$TUNNEL_PID" && echo "터널:      실행 중 (pid $(cat "$TUNNEL_PID"))"          || echo "터널:      중지됨"
    [ -f "$URL_FILE" ] && echo "공유 주소: $(cat "$URL_FILE")" || true
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  status ;;
    url)     cat "$URL_FILE" 2>/dev/null || { echo "실행 중이 아닙니다." >&2; exit 1; } ;;
    logs)    tail -f "$APP_LOG" "$TUNNEL_LOG" ;;
    *)       sed -n '2,10p' "$0"; exit 1 ;;
esac
