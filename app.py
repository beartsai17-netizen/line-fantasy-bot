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
