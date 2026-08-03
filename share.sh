#!/bin/bash
# Streamlit 대시보드를 Cloudflare 퀵 터널로 외부 공유
# 사용법: ./share.sh   (중지: Ctrl+C — 터널과 앱이 함께 종료됨)

set -e
cd "$(dirname "$0")"
PORT=8765

# 이미 떠 있지 않으면 Streamlit 시작
if ! curl -s -o /dev/null "http://localhost:$PORT"; then
    echo "Streamlit 시작 중 (port $PORT)..."
    .venv/bin/streamlit run app.py --server.headless true --server.port $PORT &
    STREAMLIT_PID=$!
    trap 'kill $STREAMLIT_PID 2>/dev/null' EXIT
    until curl -s -o /dev/null "http://localhost:$PORT"; do sleep 1; done
fi

echo ""
echo "Cloudflare 터널 시작 — 아래에 표시되는 https://xxxx.trycloudflare.com 주소를 공유하세요."
echo "(주소는 실행할 때마다 바뀌며, 이 창을 닫으면 접속이 끊깁니다)"
echo ""
cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate
