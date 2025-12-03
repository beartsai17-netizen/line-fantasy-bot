import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from openai import OpenAI
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


# ==============================
# 讀取 .env
# ==============================
load_dotenv()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise Exception("請在 .env 設定 LINE_CHANNEL_SECRET、LINE_CHANNEL_ACCESS_TOKEN")

if not OPENAI_KEY:
    raise Exception("請在 .env 設定 OPENAI_API_KEY")


# ==============================
# 基礎設定
# ==============================
app = Flask(__name__)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_KEY)


# ==============================
# Google Sheet 指令載入
# ==============================
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
        return {row["keyword"].lower(): row["response"] for row in data}

    except Exception as e:
        print("❌ Google Sheet 載入失敗:", e)
        return {}

# ---------------------------------------
# Yahoo Fantasy OAuth Step 2
# ---------------------------------------

import base64
import urllib.parse

YAHOO_CLIENT_ID = "dj0yJmk9OUc2cmtzdEpqbVlUJmQ9WVdrOWFGYzRTREJwVW5vbWNHbzlNQT09JnM9Y29uc3VtZXJzZWNyZXQmc3Y9MCZ4PTAw"
YAHOO_CLIENT_SECRET = "a1ee51651fa5aa723cd21f0d8160edc90a22997a"

# 你的 Render 網址（請改成你的）
REDIRECT_URI = "https://line-fantasy-bot.onrender.com/yahoo/callback"


@app.route("/yahoo/callback")
def yahoo_callback():
    code = request.args.get("code")

    if not code:
        return "Yahoo 授權失敗：沒有取得 code"

    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    # Basic Auth 構造方式：base64("client_id:client_secret")
    auth_str = f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}"
    basic_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code
    }

    # ⚠️ Yahoo 要求 data 一定是 form-encoded，而不是 JSON
    response = requests.post(token_url, headers=headers, data=data)

    try:
        result = response.json()
    except:
        return f"Token API 回傳非 JSON：{response.text}"

    # 檢查是否有錯誤
    if "error" in result:
        return f"Yahoo Token 換取失敗：{result}"

    # 成功
    return jsonify(result)


# ==============================
# LINE Webhook
# ==============================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    print("🔵 Request body:", body)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Handler Error:", e)
        abort(400)

    return "OK"


# ==============================
# 處理文字訊息
# ==============================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):

    # 忽略 LINE 自動重送
    if event.delivery_context.is_redelivery:
        print("🔁 忽略重送訊息 (isRedelivery = true)")
        return

    user_text = event.message.text.strip()

    # 規則：只有 "!" 開頭才回應
    if not user_text.startswith("!"):
        return

    # 拆解指令（!指令 參數）
    parts = user_text[1:].split(" ", 1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # ==============================
    # A. Fantasy (保留空殼)
    # ==============================
    if command == "ff":
        reply_text = f"[Fantasy 指令收到] 參數：{argument}"

    # ==============================
    # B. ChatGPT
    # ==============================
    elif command == "bot":
        if argument == "":
            reply_text = "請在 !bot 後加上你要問 ChatGPT 的問題喔！"
        else:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是一個友善的聊天助手，回答簡潔自然。"},
                        {"role": "user", "content": argument},
                    ],
                )
                reply_text = response.choices[0].message.content
            except Exception as e:
                reply_text = f"ChatGPT 發生錯誤：{e}"

    # ==============================
    # C. Google Sheet 自訂指令
    # ==============================
    else:
        sheet_commands = load_sheet_commands()
        lookup = command.lower()

        if lookup in sheet_commands:
            reply_text = sheet_commands[lookup]
        else:
            reply_text = f"查無此指令：`{command}`（請到 Google Sheet 新增 keyword）"

    # ==============================
    # 回覆使用者
    # ==============================
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


# ==============================
# Render 啟動設定
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


