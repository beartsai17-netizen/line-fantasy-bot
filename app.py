import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from openai import OpenAI
import requests
import os

from flask import Flask, request, abort
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


# ----------------------------
# Load ENV
# ----------------------------
load_dotenv()
NBA_RELAY_URL = os.getenv("NBA_RELAY_URL")

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if CHANNEL_SECRET is None or CHANNEL_ACCESS_TOKEN is None:
    raise Exception("請先在 .env 設定 LINE_CHANNEL_SECRET 和 LINE_CHANNEL_ACCESS_TOKEN")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ----------------------------
# Flask + LINE SDK
# ----------------------------
app = Flask(__name__)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    print("Request body:", body)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("Error in handler:", e)
        abort(400)

    return "OK"


# ----------------------------
# Google Sheet Commands
# ----------------------------
def load_sheet_commands():
    try:
        credentials_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(
            credentials_info,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(os.getenv("GOOGLE_SHEET_URL")).sheet1

        data = sheet.get_all_records()
        commands = {row["keyword"].lower(): row["response"] for row in data}
        return commands

    except Exception as e:
        print("Error loading Google Sheet:", e)
        return {}


# ----------------------------
# NBA (Using Relay Server)
# ----------------------------
def nba_search_player(name):
    try:
        url = f"{NBA_RELAY_URL}/search?name={name}"
        data = requests.get(url).json()

        rows = data["resultSets"][0]["rowSet"]
        if not rows:
            return None

        r = rows[0]
        return {
            "id": r[0],
            "name": r[1],
            "team": r[4],
        }

    except Exception as e:
        print("NBA search error:", e)
        return None


def nba_latest_game(player_id):
    try:
        url = f"{NBA_RELAY_URL}/latest?player_id={player_id}"
        data = requests.get(url).json()

        rows = data["resultSets"][0]["rowSet"]
        if not rows:
            return None

        g = rows[0]
        return {
            "matchup": g[5],
            "pts": g[26],
            "reb": g[20],
            "ast": g[21],
            "stl": g[22],
            "blk": g[23],
            "fg_pct": g[11],
        }

    except Exception as e:
        print("NBA latest game error:", e)
        return None


# ----------------------------
# Handle LINE Messages
# ----------------------------
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):

    if event.delivery_context.is_redelivery:
        print("🔁 忽略重送訊息")
        return

    user_text = event.message.text.strip()

    if not user_text.startswith("!"):
        return

    parts = user_text[1:].split(" ", 1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # ----------------------------
    # A. Fantasy
    # ----------------------------
    if command == "ff":
        reply_text = f"[Fantasy 指令收到] 參數：{argument}"

    # ----------------------------
    # B. NBA
    # ----------------------------
    elif command == "nba":
        if argument == "":
            reply_text = "請輸入球員名稱，例如：!nba SGA"
        else:
            player = nba_search_player(argument)

            if player is None:
                reply_text = f"找不到球員：{argument}"
            else:
                stats = nba_latest_game(player["id"])

                if stats is None:
                    reply_text = f"{player['name']} 尚無比賽數據"
                else:
                    reply_text = (
                        f"{player['name']} 最新一場比賽：\n"
                        f"對手：{stats['matchup']}\n"
                        f"得分：{stats['pts']}\n"
                        f"籃板：{stats['reb']}\n"
                        f"助攻：{stats['ast']}\n"
                        f"抄截：{stats['stl']}\n"
                        f"阻攻：{stats['blk']}\n"
                        f"命中率：{stats['fg_pct'] * 100:.1f}%"
                    )

    # ----------------------------
    # C. ChatGPT
    # ----------------------------
    elif command == "bot":
        if argument == "":
            reply_text = "請在 !bot 後面輸入問題！"
        else:
            try:
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是一個友善的助手，回答簡潔自然。"},
                        {"role": "user", "content": argument},
                    ],
                )
                reply_text = res.choices[0].message.content
            except Exception as e:
                reply_text = f"ChatGPT 發生錯誤：{e}"

    # ----------------------------
    # D. Google Sheet
    # ----------------------------
    else:
        sheet_commands = load_sheet_commands()
        lookup = command.lower()

        reply_text = sheet_commands.get(
            lookup, f"查無此指令：`{command}`（請到 Google Sheet 新增 keyword）"
        )

    # 回覆訊息
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
