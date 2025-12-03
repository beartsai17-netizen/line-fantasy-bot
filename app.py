import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

# 處理文字訊息事件
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    user_text = event.message.text.strip()

    # 規則：只有 "!" 開頭才回應
    if not user_text.startswith("!"):
        return

    # 拆解使用者訊息
    parts = user_text[1:].split(" ", 1)
    command = parts[0].lower()             # 第一段（!後面的字）
    argument = parts[1] if len(parts) > 1 else ""  # 之後的文字

    # 第一層：三大專用指令
    if command == "ff":
        reply_text = f"[Fantasy 指令收到] 參數：{argument}"
    
    elif command == "nba":
        reply_text = f"[NBA 指令收到] 參數：{argument}"

    elif command == "bot":
        reply_text = f"[ChatGPT 指令收到] 參數：{argument}"

    # 第二層：fallback → 之後會放 Google Sheet 查詢
    else:
        reply_text = f"[GoogleSheet 指令] `{command}`（目前先回測試訊息）"

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




