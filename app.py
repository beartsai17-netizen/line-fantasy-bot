import json
import base64
import urllib.parse
import gspread
import requests
import datetime

from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI

import os
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    MessagingApi,
    ApiClient,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent


# ==============================
# Load .env
# ==============================
load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise Exception("缺少 LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN")

if not OPENAI_KEY:
    raise Exception("缺少 OPENAI_API_KEY")

app = Flask(__name__)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_KEY)


# ==============================
# Google Sheet Utils
# ==============================
def get_gsheet():
    credentials_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
        credentials_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    gc = gspread.authorize(credentials)
    return gc.open_by_url(os.getenv("GOOGLE_SHEET_URL"))


def load_sheet_commands():
    try:
        sheet = get_gsheet().worksheet("keyword_reply")
        rows = sheet.get_all_records()
        return {row["keyword"].lower(): row["response"] for row in rows}
    except Exception as e:
        print("❌ Google Sheet 載入失敗:", e)
        return {}


# ==============================
# Yahoo Fantasy OAuth
# ==============================
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET")

REDIRECT_URI = "https://line-fantasy-bot.onrender.com/yahoo/callback"

YAHOO_LEAGUE_KEY = os.getenv("YAHOO_LEAGUE_KEY") 

if not YAHOO_LEAGUE_KEY:
    print("⚠️ 尚未設定 YAHOO_LEAGUE_KEY，Fantasy 查詢會無法使用")

# Yahoo Step 1：Login URL
@app.route("/yahoo/login")
def yahoo_login():
    auth_url = (
        "https://api.login.yahoo.com/oauth2/request_auth?"
        f"client_id={YAHOO_CLIENT_ID}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        "response_type=code&"
        "language=en-us"
    )
    return f"<a href='{auth_url}'>點此登入 Yahoo Fantasy</a>"


# Yahoo Step 2：Callback -> Exchange Token
@app.route("/yahoo/callback")
def yahoo_callback():
    code = request.args.get("code")
    if not code:
        return "❌ 授權失敗：缺少 code"

    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    # Basic Authentication
    auth_str = f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}"
    basic_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    response = requests.post(token_url, headers=headers, data=data)
    try:
        result = response.json()
    except:
        return f"❌ Token API 回傳非 JSON：{response.text}"

    if "error" in result:
        return f"❌ Token 換取失敗：{result}"

    save_yahoo_token(
        result["access_token"],
        result["refresh_token"],
        result["expires_in"]
    )

    return "Yahoo Token 已成功儲存！你可以關閉這個視窗。"


# ==============================
# Token Storage
# ==============================
def save_yahoo_token(access_token, refresh_token, expires_in):
    try:
        expires_at = (datetime.datetime.utcnow() +
                      datetime.timedelta(seconds=expires_in)).isoformat()

        ws = get_gsheet().worksheet("yahoo_token")

        # MUST use 2D array format
        ws.update("B2", [[access_token]])
        ws.update("B3", [[refresh_token]])
        ws.update("B4", [[expires_at]])

        print("✅ Token 寫入成功")

    except Exception as e:
        print("❌ Token 寫入失敗：", e)


def load_yahoo_token():
    try:
        ws = get_gsheet().worksheet("yahoo_token")
        access_token = ws.acell("B2").value
        refresh_token = ws.acell("B3").value
        expires_at = ws.acell("B4").value
        return access_token, refresh_token, expires_at
    except Exception as e:
        print("❌ Token 讀取失敗：", e)
        return None, None, None


# ==============================
# Auto Refresh Yahoo Token
# ==============================
def refresh_yahoo_token_if_needed():
    access_token, refresh_token, expires_at = load_yahoo_token()

    if not access_token or not refresh_token or not expires_at:
        return access_token  # token 不存在，返回 None

    expires_at_dt = datetime.datetime.fromisoformat(expires_at)
    now = datetime.datetime.utcnow()

    # 若 token 已過期 60 秒前，就 refresh
    if now > expires_at_dt - datetime.timedelta(seconds=60):
        print("🔄 Token 已過期，開始 refresh...")

        token_url = "https://api.login.yahoo.com/oauth2/get_token"

        auth_str = f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}"
        basic_auth = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": REDIRECT_URI,
        }

        res = requests.post(token_url, headers=headers, data=data)
        result = res.json()

        if "access_token" in result:
            save_yahoo_token(
                result["access_token"],
                result.get("refresh_token", refresh_token),
                result["expires_in"]
            )
            return result["access_token"]

        print("❌ Refresh Token 失敗：", result)

    return access_token

def yahoo_api_get(path: str):
    """
    Yahoo Fantasy API 共用 GET 函式。
    path 例如： 'league/{league_key}/players;search=SGA;count=5'
    會自動：
    1. 先呼叫 refresh_yahoo_token_if_needed() 拿 access_token
    2. 用 Bearer token 呼叫 Yahoo Fantasy API
    3. 回傳 JSON（或 None）
    """
    token = refresh_yahoo_token_if_needed()
    if not token:
        print("⚠️ 尚未有 Yahoo Token，請先到 /yahoo/login 授權一次")
        return None

    url = f"https://fantasysports.yahooapis.com/fantasy/v2/{path}?format=json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print("❌ Yahoo API 呼叫失敗：", res.status_code, res.text[:200])
        return None

    try:
        return res.json()
    except Exception as e:
        print("❌ Yahoo API JSON 解析失敗：", e, res.text[:200])
        return None

def yahoo_search_player_by_name(name: str):
    if not YAHOO_LEAGUE_KEY:
        print("⚠️ 尚未設定 YAHOO_LEAGUE_KEY")
        return None

    encoded_name = urllib.parse.quote(name)
    path = f"league/{YAHOO_LEAGUE_KEY}/players;search={encoded_name};count=5"

    data = yahoo_api_get(path)
    if not data:
        return None

    try:
        league = data["fantasy_content"]["league"]
        players_obj = league[1]["players"]
        count = int(players_obj["count"])

        if count == 0:
            return None

        # 取第一筆玩家
        raw_player = players_obj["0"]["player"]

        # 玩家資料實際是雙層 list：player[0] 才是真資料陣列
        info_list = raw_player[0]  

        player_key = None
        name_full = None
        team = ""

        for block in info_list:
            if not isinstance(block, dict):
                continue
            if "player_key" in block:
                player_key = block["player_key"]
            if "name" in block:
                name_full = block["name"]["full"]
            if "editorial_team_abbr" in block:
                team = block["editorial_team_abbr"]

        if not player_key:
            return None

        return {
            "player_key": player_key,
            "name": name_full or name,
            "team": team,
        }

    except Exception as e:
        print("❌ 解析 Yahoo 玩家搜尋結果失敗：", e)
        print(json.dumps(data, indent=2))
        return None



def yahoo_get_player_season_avg(player_key: str):
    """
    抓 Yahoo Fantasy 本季「場均」數據
    """
    path = f"player/{player_key}/stats;type=season"
    data = yahoo_api_get(path)
    if not data:
        return None

    try:
        player_arr = data["fantasy_content"]["player"]

        stats_block = None
        for part in player_arr:
            if isinstance(part, dict) and "player_stats" in part:
                stats_block = part["player_stats"]
                break

        if not stats_block:
            return None

        stats_list = stats_block["stats"]

        stat_map = {}
        for s in stats_list:
            stat = s.get("stat", {})
            stat_id = stat.get("stat_id")
            value = stat.get("value")
            if stat_id is not None:
                stat_map[stat_id] = value

        return stat_map

    except Exception as e:
        print("❌ 解析 season avg 失敗：", e)
        return None

def yahoo_get_player_stats_by_date_range(player_key: str, days: int = 7):
    """
    抓某球員「最近 N 天」的數據（逐日 stats → 累積 → 回傳 stat_id -> total_value）
    """
    all_stats = {}  # stat_id 累積值

    today = datetime.date.today()

    for d in range(days):
        date = today - datetime.timedelta(days=d)
        date_str = date.strftime("%Y-%m-%d")

        path = f"player/{player_key}/stats;type=date;date={date_str}"
        data = yahoo_api_get(path)

        if not data:
            continue

        try:
            player_arr = data["fantasy_content"]["player"]

            stats_block = None
            for part in player_arr:
                if isinstance(part, dict) and "player_stats" in part:
                    stats_block = part["player_stats"]
                    break

            if not stats_block:
                continue

            stats_list = stats_block["stats"]

            for s in stats_list:
                stat = s.get("stat", {})
                stat_id = stat.get("stat_id")
                value = stat.get("value")

                if stat_id is None or value in [None, "", "-"]:
                    continue

                try:
                    v = float(value)
                except:
                    continue

                all_stats[stat_id] = all_stats.get(stat_id, 0) + v

        except Exception as e:
            print("❌ 日期 stats 解析失敗：", e)
            continue

    return all_stats

# ==============================
# 動態讀取聯盟 stat 設定 & 格式化球員數據
# ==============================

STAT_LABEL_MAP = None  # display_name -> stat_id 的對照表（例如 "PTS" -> "25"）

# 想要顯示的欄位（左邊是我們想顯示的 label，用來排順序）
DESIRED_LABELS = [
    "PTS",   # 得分
    "REB",   # 籃板
    "AST",   # 助攻
    "STL",   # 抄截
    "BLK",   # 火鍋
    "FG%",   # 命中率
    "FT%",   # 罰球命中率
    "3PTM",  # 場均三分命中數
    "3PT%",  # 三分命中率
    "TO",    # 失誤
]

# 各項目可能在 Yahoo 裡的名稱（有些聯盟會用 ST / STL 或 3PTM / 3PM 等）
LABEL_CANDIDATES = {
    "PTS":  ["PTS"],
    "REB":  ["REB"],
    "AST":  ["AST"],
    "STL":  ["ST", "STL"],
    "BLK":  ["BLK"],
    "FG%":  ["FG%", "FG PCT"],
    "FT%":  ["FT%", "FT PCT"],
    "3PTM": ["3PTM", "3PM", "3-PTM"],
    "3PT%": ["3PT%", "3P%", "3-PT%"],
    "TO":   ["TO", "TOV", "TURNOVERS"],
}

def load_stat_label_map():
    """
    呼叫 league/{league_key}/settings，建立 display_name -> stat_id 的 mapping。
    只會在第一次用到時打 API，之後都用快取。
    """
    global STAT_LABEL_MAP

    if STAT_LABEL_MAP is not None:
        return STAT_LABEL_MAP

    if not YAHOO_LEAGUE_KEY:
        print("⚠️ 尚未設定 YAHOO_LEAGUE_KEY，無法載入 stat 設定")
        STAT_LABEL_MAP = {}
        return STAT_LABEL_MAP

    data = yahoo_api_get(f"league/{YAHOO_LEAGUE_KEY}/settings")
    if not data:
        STAT_LABEL_MAP = {}
        return STAT_LABEL_MAP

    try:
        league = data["fantasy_content"]["league"]

        settings_block = None
        for part in league:
            if isinstance(part, dict) and "settings" in part:
                settings_block = part["settings"][0]
                break

        if not settings_block:
            print("⚠️ 找不到 settings 區塊")
            STAT_LABEL_MAP = {}
            return STAT_LABEL_MAP

        stats = settings_block["stat_categories"]["stats"]
        label_map = {}

        # 例如 stat 裡會長這樣：
        # {
        #   "stat": {
        #       "stat_id": "5",
        #       "name": "FGM",
        #       "display_name": "FGM",
        #       ...
        #   }
        # }
        for item in stats:
            stat = item["stat"]
            stat_id = stat["stat_id"]
            label = stat.get("display_name") or stat.get("name")
            if label:
                label_map[label] = stat_id

        STAT_LABEL_MAP = label_map
        print("✅ 已載入 league stat 設定：", STAT_LABEL_MAP)
        return STAT_LABEL_MAP

    except Exception as e:
        print("❌ 解析 league settings 失敗：", e)
        STAT_LABEL_MAP = {}
        return STAT_LABEL_MAP


def _find_stat_id_for_label(label: str, label_map: dict):
    """從 STAT_LABEL_MAP 裡，用 candidates 找到對應的 stat_id"""
    candidates = LABEL_CANDIDATES.get(label, [label])
    for cand in candidates:
        if cand in label_map:
            return label_map[cand]
    return None


def format_player_stats(stats: dict):
    """
    將 Yahoo 回傳的 season stats 轉成場均格式：
    PTS / REB / AST / STL / BLK / FG% / FT% / 3PTM / 3PT% / TO
    """

    label_map = load_stat_label_map()

    # ------------------------
    # 先處理場次（GP）
    # ------------------------
    gp = None

    # stats["0"] 通常就是出賽場數
    if "0" in stats:
        try:
            gp = float(stats["0"])
        except:
            gp = None

    print("🔎 Games played (from stats['0']):", gp)

    lines = []

    for label in DESIRED_LABELS:
        stat_id = _find_stat_id_for_label(label, label_map)
        if not stat_id:
            continue

        raw_val = stats.get(str(stat_id))
        if raw_val is None or raw_val == "":
            continue

        try:
            v = float(raw_val.replace("%", "")) if isinstance(raw_val, str) else float(raw_val)
        except:
            lines.append(f"{label}: {raw_val}")
            continue

        # 場均數據
        if label in ["PTS", "REB", "AST", "STL", "BLK", "3PTM", "TO"]:
            if gp and gp > 0:
                per_game = v / gp
                lines.append(f"{label}: {per_game:.1f}")
            else:
                lines.append(f"{label}: {v}")

        # 百分比
        elif label in ["FG%", "FT%", "3PT%"]:
            if v > 1:
                v = v / 100
            lines.append(f"{label}: {v:.3f}")

    if not lines:
        return "尚無可讀數據"

    return "\n".join(lines)

def format_player_recent_avg(stats: dict, days: int):
    """
    把最近 N 天累積 stats → 換算成「場均」
    """
    if not stats:
        return "最近沒有比賽數據"

    # 先用季 stats 的 formatter（它會處理 FG%、FT% 等百分比）
    # 但需要告知 formatter：這不是累積而是要除以天數
    per_game_stats = {}

    for stat_id, total in stats.items():
        try:
            per_game_stats[stat_id] = float(total) / days
        except:
            per_game_stats[stat_id] = total

    return format_player_stats(per_game_stats)


    # DEBUG：你也可以暫時印出看看原始 stats & label_map
    print("🔎 Raw stats:", stats)
    print("🔎 Label map:", label_map)
    print("🔎 Games played (gp):", gp)

    lines = []

    for label in DESIRED_LABELS:
        stat_id = _find_stat_id_for_label(label, label_map)
        if not stat_id:
            continue

        raw_val = stats.get(stat_id)
        if raw_val is None or raw_val == "":
            continue

        try:
            v = float(raw_val)
        except Exception:
            # 偶爾會是字串，直接顯示
            lines.append(f"{label}: {raw_val}")
            continue

        # 計數型：換算成「本季場均」
        if label in ["PTS", "REB", "AST", "STL", "BLK", "3PTM", "TO"]:
            if gp and gp > 0:
                per_game = v / gp
                lines.append(f"{label}: {per_game:.1f}")
            else:
                lines.append(f"{label}: {v}")

        # 百分比型：用 0.XXX 千分比顯示
        elif label in ["FG%", "FT%", "3PT%"]:
            # 如果 Yahoo 給的是 47.1 就除以 100；如果本來就是 0.471 就直接用
            if v > 1:
                v = v / 100.0
            lines.append(f"{label}: {v:.3f}")

    if not lines:
        return "尚無可讀數據"

    return "\n".join(lines)



def yahoo_get_my_leagues():
    data = yahoo_api_get("users;use_login=1/games;game_keys=nba/leagues")

    if not data:
        return None

    try:
        users = data["fantasy_content"]["users"]
        user0 = users["0"]["user"][1]
        games = user0["games"]

        league_keys = []

        for i in range(int(games["count"])):
            leagues = games[str(i)]["game"][1]["leagues"]
            for j in range(int(leagues["count"])):
                league_key = leagues[str(j)]["league"][0]["league_key"]
                league_keys.append(league_key)

        return league_keys

    except Exception as e:
        print("解析 league 列表失敗：", e)
        return None



# ==============================
# LINE Webhook
# ==============================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return "OK"


# ==============================
# LINE Message Handler
# ==============================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):

    if event.delivery_context.is_redelivery:
        print("🔁 忽略重送訊息")
        return

    user_text = event.message.text.strip()

    if not user_text.startswith("!"):
        return

    parts = user_text[1:].split(" ", 1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # Fantasy Module
    if command == "ff":
        reply_text = f"[Fantasy 指令收到] 參數：{argument}"

    elif command == "player":
        if not argument:
            reply_text = "請在 !player 後面加球員名字，例如：!player SGA"
        else:
            player = yahoo_search_player_by_name(argument)
            if not player:
                reply_text = f"找不到球員：{argument}"
            else:
                stats = yahoo_get_player_season_avg(player["player_key"])
                if not stats:
                    reply_text = f"{player['name']} 暫時查不到 stats"
                else:
                    # ✅ 這裡改成呼叫 format_player_stats
                    pretty_stats = format_player_stats(stats)
                    reply_text = (
                        f"📊 {player['name']}（{player['team']}）\n"
                        f"—— 本季場均 ——\n"
                        f"{pretty_stats}"
                    )
                    
    elif command == "player_week":
        if not argument:
            reply_text = "請在 !player_week 後面加球員名字，例如：!player_week curry"
        else:
            player = yahoo_search_player_by_name(argument)
            if not player:
                reply_text = f"找不到球員：{argument}"
            else:
                stats7 = yahoo_get_player_stats_by_date_range(player["player_key"], days=7)
                pretty = format_player_recent_avg(stats7, 7)
                reply_text = (
                    f"📆 {player['name']}（{player['team']}）\n"
                    f"—— 最近 7 天場均 ——\n"
                    f"{pretty}"
                )

    elif command == "player_2week":
        if not argument:
            reply_text = "請在 !player_2week 後面加球員名字，例如：!player_2week curry"
        else:
            player = yahoo_search_player_by_name(argument)
            if not player:
                reply_text = f"找不到球員：{argument}"
            else:
                stats14 = yahoo_get_player_stats_by_date_range(player["player_key"], days=14)
                pretty = format_player_recent_avg(stats14, 14)
                reply_text = (
                    f"📆 {player['name']}（{player['team']}）\n"
                    f"—— 最近 14 天場均 ——\n"
                    f"{pretty}"
                )
    
                            
    elif command == "leagues":
        leagues = yahoo_get_my_leagues()
        if not leagues:
            reply_text = "無法取得 league 列表，請先確認 token 是否授權"
        else:
            reply_text = "你的 Yahoo Fantasy League Keys：\n" + "\n".join(leagues)

 
    # ChatGPT
    elif command == "bot":
        if not argument:
            reply_text = "請輸入問題"
        else:
            try:
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是一個友善的聊天助手。"},
                        {"role": "user", "content": argument},
                    ],
                )
                reply_text = res.choices[0].message.content
            except Exception as e:
                reply_text = f"ChatGPT 錯誤：{e}"

    else:
        cmds = load_sheet_commands()
        reply_text = cmds.get(command, f"查無指令：{command}")

    # Reply Message
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


# ==============================
# Start Server
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)



















