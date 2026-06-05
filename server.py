#!/usr/bin/env python3
"""
配信スケジュール自動同期サーバー
Google Sheets の3アカウント分を30秒ごとに取得して Web アプリに反映します
"""

import csv, io, json, os, re, sys, time, threading, urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

SHEETS_ID = "1fmLHEJT9U20LPKLS-Med9cu2NJxhmjfD4gb-nOJwW9M"
SERVE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT      = int(os.environ.get("PORT", 8765))
INTERVAL  = 30  # 秒

# アカウント設定: app_id → (gid, イベントIDプレフィックス)
ACCOUNTS = {
    "account1": (1509085180, "ev_tori"),     # とりま〜けっと
    "account2": (1331827288, "ev_seikai"),   # 正解良品
    "account3": (1116290429, "ev_lumina"),   # LUMINA STUDIO
    # account4 (るみな) はシートなし
}

COLORS = ["#fe2c55","#ff9500","#25f4ee","#34c759",
          "#af52de","#ff6b6b","#007aff","#ffcc00"]
EMOJIS = {
    "松田":"😊","川上":"😎","野沢":"🥰","陶":"🤩",
    "あかり":"🌸","淳子":"🌿","戸井田":"💫",
    "喜納":"🔥","安倍":"⭐","水野":"💧","緒環":"🌙",
    "織田澤":"👑","柴田":"🌟",
}

# 名前の表記ゆれ統合
NAME_ALIASES = {
    "安部": "安倍",   # 表記ゆれ
}

# この名前のみメンバーとして登録する（それ以外はメモ扱い）
ALLOWED_MEMBERS = {
    "あかり", "織田澤", "柴田", "淳子",
    "喜納", "安倍", "戸井田", "水野",
    "緒環", "松田", "川上", "野沢", "陶",
}

CACHE = {"data": None, "updated_at": 0}
LOCK  = threading.Lock()


def get_member(name, members_pool):
    """グローバルメンバープールにメンバーを登録してIDを返す"""
    name = name.strip()
    if not name or name in ("なし", "-"):
        return None
    # エイリアス統合（例: 戸井田 → あやち）
    name = NAME_ALIASES.get(name, name)
    # 許可リスト外はメンバー登録しない
    if name not in ALLOWED_MEMBERS:
        return None
    mid = f"member_{name}"
    if mid not in members_pool:
        members_pool[mid] = {
            "id":       mid,
            "name":     name,
            "iconType": "emoji",
            "emoji":    EMOJIS.get(name, "👤"),
            "imgData":  None,
            "color":    COLORS[len(members_pool) % len(COLORS)],
        }
    return mid


def parse_sheet(rows, ev_prefix, members_pool):
    """シートの行リストからイベントリストを生成（日付引き継ぎ対応）"""
    events    = []
    last_date = None

    for row in rows[1:]:  # 0行目はヘッダー
        # 列数が足りない行はスキップ
        if len(row) < 4:
            continue

        date_str = str(row[0]).strip()
        start    = str(row[2]).strip()
        end      = str(row[3]).strip()
        streamer = NAME_ALIASES.get(str(row[5]).strip(), str(row[5]).strip()) if len(row) > 5 else ""
        moder    = NAME_ALIASES.get(str(row[6]).strip(), str(row[6]).strip()) if len(row) > 6 else ""

        # 日付の引き継ぎ（空セルは前の日付を使う）
        if re.match(r'\d+/\d+', date_str):
            last_date = date_str
        elif not date_str and last_date:
            date_str = last_date
        else:
            continue

        # 時間が無効な行はスキップ
        if not start or not re.match(r'\d+:\d+', start):
            continue
        if not end or not re.match(r'\d+:\d+', end):
            continue

        m, d      = date_str.split("/")
        date_full = f"2026-{int(m):02d}-{int(d):02d}"

        sid = get_member(streamer, members_pool)
        mid = get_member(moder,    members_pool)

        title = streamer if streamer else "配信"
        if moder and moder not in ("なし", "-", ""):
            title += f" / {moder}"

        sh, sm = start.split(":")[:2]   # 秒付き "HH:MM:SS" にも対応
        eh, em = end.split(":")[:2]

        events.append({
            "id":           f"{ev_prefix}_{len(events)+1}",
            "title":        title,
            "date":         date_full,
            "start":        f"{int(sh):02d}:{sm}",
            "end":          f"{int(eh):02d}:{em}",
            "memo":         "",
            "color":        "#fe2c55",
            "streamerIds":  [sid] if sid else [],
            "moderatorIds": [mid] if mid else [],
        })

    return events


def fetch_sheet_csv(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEETS_ID}/export?format=csv&gid={gid}"
    req = urllib.request.urlopen(url, timeout=15)
    return list(csv.reader(io.StringIO(req.read().decode("utf-8"))))


def fetch_all():
    """全アカウントのシートを取得してデータを構築"""
    members_pool = {}   # mid → メンバー情報（グローバル共有）
    account_events = {} # account_id → [events]
    errors = []

    for account_id, (gid, prefix) in ACCOUNTS.items():
        try:
            rows   = fetch_sheet_csv(gid)
            events = parse_sheet(rows, prefix, members_pool)
            account_events[account_id] = events
            print(f"  ✅ {account_id}: {len(events)} 件")
        except Exception as e:
            account_events[account_id] = []
            errors.append(f"{account_id}: {e}")
            print(f"  ❌ {account_id}: {e}")

    return {
        "accounts": account_events,
        "members":  list(members_pool.values()),
        "errors":   errors,
    }


def fetch_and_update():
    print(f"📊 Google Sheets 同期中... ({time.strftime('%H:%M:%S')})")
    try:
        data = fetch_all()
        total = sum(len(v) for v in data["accounts"].values())
        with LOCK:
            CACHE["data"]       = data
            CACHE["updated_at"] = time.time()
        print(f"✅ 合計 {total} 件 / メンバー {len(data['members'])} 名")
    except Exception as e:
        print(f"❌ 同期失敗: {e}")


def polling_loop():
    while True:
        time.sleep(INTERVAL)
        fetch_and_update()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/schedule":
            with LOCK:
                data = CACHE["data"]
                ts   = CACHE["updated_at"]

            if data is None:
                self._json({"error": "データ取得中です。しばらくお待ちください"}, 503)
                return

            self._json({**data, "updatedAt": ts})
        else:
            super().do_GET()

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"🚀 サーバー起動: http://localhost:{PORT}")
    print(f"🔗 Spreadsheet: https://docs.google.com/spreadsheets/d/{SHEETS_ID}")
    print(f"🔄 {INTERVAL} 秒ごとに自動同期（Ctrl+C で停止）\n")

    fetch_and_update()
    threading.Thread(target=polling_loop, daemon=True).start()

    try:
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 サーバーを停止しました")
        sys.exit(0)
