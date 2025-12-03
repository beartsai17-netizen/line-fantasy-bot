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

# 讀取 .env 檔案
load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if CHANNEL_SECRET is None or CHANNEL_ACCESS_TOKEN is None:
    raise Exception("請先在 .env 設定 LINE_CHANNEL_SECRET 和 LINE_CHANNEL_ACCESS_TOKEN")

app = Flask(__name__)

# LINE SDK 設定
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


@app.route("/callback", methods=["POST"])
def callback():
    # 取得 X-Line-Signature 頭
    signature = request.headers.get("X-Line-Signature", "")

    # 取得 request body
    body = request.get_data(as_text=True)

    print("Request body:", body)  # debug 用，之後可以拿掉

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("Error in handler:", e)
        abort(400)

    return "OK"

def load_sheet_commands():
    try:
        credentials_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(
            credentials_info,
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        )
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(os.getenv("GOOGLE_SHEET_URL")).sheet1

        data = sheet.get_all_records()
        commands = {row["keyword"]: row["response"] for row in data}
        return commands

    except Exception as e:
        print("Error loading Google Sheet:", e)
        return {}
        
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ------------------------------
# NBA API - balldontlie
# ------------------------------
def nba_search_player(name):
    try:
        url = f"https://api.balldontlie.io/v1/players?search={name}"
        res = requests.get(url).json()

        if res.get("data") == []:
            return None

        player = res["data"][0]  # 取第一筆最相關
        return player

    except Exception as e:
        print("NBA player search error:", e)
        return None


def nba_get_latest_stats(player_id):
    try:
        url = f"https://api.balldontlie.io/v1/stats?player_ids[]={player_id}&per_page=1"
        res = requests.get(url).json()

        if res.get("data") == []:
            return None

        game = res["data"][0]
        stats = game["stats"]
        return stats

    except Exception as e:
        print("NBA stats error:", e)
        return None


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    # 忽略 LINE 自動重送
    if event.delivery_context.is_redelivery:
        print("🔁 忽略重送訊息（isRedelivery = true）")
        return

    user_text = event.message.text.strip()

    # 規則：只有 "!" 開頭才回應
    if not user_text.startswith("!"):
        return

    # 拆解指令：!xxx yyy
    parts = user_text[1:].split(" ", 1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # ----------------------
    # (A) Fantasy（尚未串接）
    # ----------------------
    if command == "ff":
        reply_text = f"[Fantasy 指令收到] 參數：{argument}"

    # ----------------------
    # (B) NBA（已串接）
    # ----------------------
    elif command == "nba":
        if argument == "":
            reply_text = "請輸入球員名稱，例如：!nba SGA"
        else:
            player = nba_search_player(argument)

            if player is None:
                reply_text = f"找不到球員：{argument}"
            else:
                stats = nba_get_latest_stats(player["id"])

                if stats is None:
                    reply_text = (
                        f"{player['first_name']} {player['last_name']} 尚無比賽數據"
                    )
                else:
                    reply_text = (
                        f"{player['first_name']} {player['last_name']} 最新一場比賽：\n"
                        f"得分：{stats['pts']}\n"
                        f"籃板：{stats['reb']}\n"
                        f"助攻：{stats['ast']}\n"
                        f"抄截：{stats['stl']}\n"
                        f"阻攻：{stats['blk']}\n"
                        f"命中率：{stats['fg_pct'] * 100:.1f}%\n"
                    )

    # ----------------------
    # (C) ChatGPT（已串接）
    # ----------------------
    elif command == "bot":
        if argument == "":
            reply_text = "請在 !bot 後面輸入你要問的問題喔！"
        else:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是一個友善的聊天助手，回答簡潔自然。"},
                        {"role": "user", "content": argument}
                    ]
                )
                reply_text = response.choices[0].message.content
            except Exception as e:
                reply_text = f"ChatGPT 發生錯誤：{e}"

    # ----------------------
    # (D) Google Sheet 指令
    # ----------------------
    else:
        sheet_commands = load_sheet_commands()
        lower_index = {k.lower(): v for k, v in sheet_commands.items()}
        lookup_key = command.lower()

        if lookup_key in lower_index:
            reply_text = lower_index[lookup_key]
        else:
            reply_text = f"查無此指令：`{command}`（請到 Google Sheet 新增 keyword）"

    # ----------------------
    # 最後回覆使用者
    # ----------------------
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















