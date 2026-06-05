#!/bin/bash
cd "$(dirname "$0")"

# 既存のサーバーを停止
lsof -ti:8765 | xargs kill -9 2>/dev/null

echo "🚀 スケジュールサーバーを起動中..."
python3 server.py &
SERVER_PID=$!

# 起動待ち
sleep 1

# ブラウザを開く
open "http://localhost:8765"

echo "✅ ブラウザを開きました"
echo "🔄 Numbersファイルを保存すると30秒以内に自動反映されます"
echo "🛑 このウィンドウを閉じるとサーバーが停止します"

# サーバープロセスを待機
wait $SERVER_PID
