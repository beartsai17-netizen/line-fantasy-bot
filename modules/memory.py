# modules/memory.py
import datetime
from modules.sheet_utils import get_gsheet


def save_group_message(event, text: str):
    """
    將群組訊息寫入 group_memory 分頁。
    只記錄 group 訊息，一般 1:1 聊天不記錄。
    """
    try:
        if event.source.type != "group":
            return

        sheet = get_gsheet().worksheet("group_memory")

        ts = datetime.datetime.now().isoformat()
        group_id = event.source.group_id
        # 目前寫入的是 user_id，如未來想要顯示暱稱可再加一層 mapping
        user = event.source.user_id

        sheet.append_row([ts, group_id, user, text])

    except Exception as e:
        print("❌ 無法寫入聊天記錄:", e)


def load_group_memory(group_id: str, limit: int = 80) -> str:
    """
    從 group_memory 分頁讀取指定 group_id 的最新 N 則訊息，
    並組成文字給 LLM 當作 context 使用。
    """
    try:
        sheet = get_gsheet().worksheet("group_memory")
        rows = sheet.get_all_records()

        msgs = [r for r in rows if str(r["group_id"]) == str(group_id)]
        msgs = msgs[-limit:]  # 取最新 N 則

        memory_text = ""
        for m in msgs:
            memory_text += f"{m['user']}: {m['text']}\n"

        return memory_text

    except Exception as e:
        print("❌ 無法讀取群組記憶:", e)
        return ""

