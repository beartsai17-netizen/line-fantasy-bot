import json
import base64
import urllib.parse
import gspread
import requests

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


# ==============================
# Yahoo Fantasy OAuth 設定
# ==============================
YAHOO_CLIENT_ID = "dj0yJmk9OUc2cmtzdEpqbVlUJmQ9WVdrOWFGYzRTREJwVW5vbWNHbzlNQT09JnM9Y29uc3VtZXJzZWNyZXQmc3Y9MCZ4PTAw"
YAHOO_CLIENT_SECRET = "a1ee51651fa5aa723cd21f0d8160edc90a22997a"

REDIRECT_URI = "https://line-fantasy-bot.onrender.com/yahoo/callback"


# ==============================
# Yahoo OAuth Step 1：登入入口
# ==============================
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


# ==============================
# Yahoo OAuth Step 2：Callback 換 Token
# ==============================
@app.route("/yahoo/callback")
def yahoo_callback():
    code = request.args.get("code")

    if not code:
        return "Yahoo 授權失敗：缺少 code"

    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    # Basic Auth
    auth_str = f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}"
    basic_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

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
        return f"Token API 回傳非 JSON：{response.text}"

    if "error" in result:
        return f"Yahoo Token 換取失敗：{result}"

    # 💥💥💥 注意：這段必須縮排在函式裡面！
    save_yahoo_token(
        result["access_token"],
        result["refresh_token"],
        result["expires_in"]
    )

    return "Yahoo Token 已成功儲存！你可以關閉這個視窗。"


def save_yahoo_token(access_token, refresh_token, expires_in):
    try:
        import datetime
        expires_at = (datetime.datetime.utcnow() +
                      datetime.timedelta(seconds=expires_in)).isoformat()

        credentials_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(
            credentials_info,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )

        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(os.getenv("GOOGLE_SHEET_URL"))
        ws = sheet.worksheet("yahoo_token")

        ws.update("B2", access_token)
        ws.update("B3", refresh_token)
        ws.update("B4", expires_at)

        print("✅ Yahoo Token 已成功寫入 Google Sheet")

    except Exception as e:
        print("❌ Token 寫入失敗：", e)

def load_yahoo_token():
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
        sheet = gc.open_by_url(os.getenv("GOOGLE_SHEET_URL"))
        ws = sheet.worksheet("yahoo_token")

        access_token = ws.acell("B2").value
        refresh_token = ws.acell("B3").value
        expires_at = ws.acell("B4").value

        return access_token, refresh_token, expires_at

    except Exception as e:
        print("❌ Token 載入失敗：", e)
        return None, None, None

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

    if event.delivery_context.is_redelivery:
        print("🔁 忽略重送訊息")
        return

    user_text = event.message.text.strip()

    if not user_text.startswith("!"):
        return

    parts = user_text[1:].split(" ", 1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # Fantasy
    if command == "ff":
        reply_text = f"[Fantasy 指令收到] 參數：{argument}"

    # ChatGPT
    elif command == "bot":
        if argument == "":
            reply_text = "請在 !bot 後加你要問的內容"
        else:
            try:
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是一個友善的聊天助手，回答簡潔自然。"},
                        {"role": "user", "content": argument},
                    ],
                )
                reply_text = res.choices[0].message.content
            except Exception as e:
                reply_text = f"ChatGPT 錯誤：{e}"

    # Google Sheet 指令
    else:
        sheet_cmds = load_sheet_commands()
        key = command.lower()

        if key in sheet_cmds:
            reply_text = sheet_cmds[key]
        else:
            reply_text = f"查無此指令：{command}"

    # 回覆 LINE
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


# ==============================
# Render 啟動
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)




