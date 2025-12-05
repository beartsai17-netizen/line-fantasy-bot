# modules/sheet_utils.py
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials


def get_gsheet():
    """取得 Google Sheet 物件（整本試算表）。"""
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
    """讀取 keyword_reply 分頁，回傳 {keyword: response} dict。"""
    try:
        sheet = get_gsheet().worksheet("keyword_reply")
        rows = sheet.get_all_records()
        return {row["keyword"].lower(): row["response"] for row in rows}
    except Exception as e:
        print("❌ Google Sheet 載入失敗:", e)
        return {}

