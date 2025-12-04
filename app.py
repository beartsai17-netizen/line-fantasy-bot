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



def yahoo_get_player_season_stats(player_key: str):
    """
    先取 Yahoo 提供的 player stats（通常是本季平均 or 累積）。
    回傳一個 dict：{ stat_id: value, ... }
    """
    path = f"player/{player_key}/stats"
    data = yahoo_api_get(path)
    if not data:
        return None

    try:
        # 結構類似：
        # fantasy_content -> player -> [ {...基本資訊...}, { "player_stats": { "stats": [ { "stat": {...}}, ... ] } } ]
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
        print("❌ 解析 Yahoo 玩家 stats 失敗：", e)
        return None

# Yahoo stat_id → 可讀名稱
STAT_MAP = {
    "9004003": "GP",
    "5": "FGM",
    "6": "FGA",
    "9": "3PTM",
    "10": "PTS",
    "11": "OREB",
    "12": "DREB",
    "13": "REB",
    "14": "AST",
    "15": "STL",
    "16": "BLK",
    "17": "TO",
    "18": "FG%",
    "19": "FT%",
    "20": "3PT%",
}

def format_player_stats_pretty(stats: dict):
    """
    將 Yahoo stat_id dict → 排序後的可讀格式
    並依指定格式顯示 0.xxx 命中率
    """

    # 取值，如果沒有就顯示 "-"
    def get(sid):
        return stats.get(sid, "-")

    # 轉成 0.xxx 格式
    def pct(v):
        try:
            return f"{float(v):.3f}"
        except:
            return "-"

    # 依你指定的順序輸出
    lines = [
        f"PTS: {get('10')}",
        f"REB: {get('13')}",
        f"AST: {get('14')}",
        f"STL: {get('15')}",
        f"BLK: {get('16')}",
        f"TO: {get('17')}",
        f"FG%: {pct(get('18'))}",
        f"FT%: {pct(get('19'))}",
        f"3PTM: {get('9')}",
        f"3PT%: {pct(get('20'))}",
    ]

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

    elif command == "token":
        token = refresh_yahoo_token_if_needed()
        reply_text = f"目前 Token：{token[:20]}..."

    elif command == "player":
        if not argument:
            reply_text = "請在 !player 後面加球員名字，例如：!player SGA"
        else:
            if not YAHOO_LEAGUE_KEY:
                reply_text = "尚未設定 YAHOO_LEAGUE_KEY，請先在環境變數設定。"
            else:
                player = yahoo_search_player_by_name(argument)
                if not player:
                    reply_text = f"找不到球員：{argument}"
                else:
                    stats = yahoo_get_player_season_stats(player["player_key"])
                    if not stats:
                        reply_text = f"{player['name']} 暫時查不到 stats"
                    else:
                        pretty_stats = format_player_stats(stats)
                        reply_text = (
                            f"📊 {player['name']}（{player['team']}）\n"
                            f"—— 本季數據 ——\n"
                            f"{pretty_stats}"
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








