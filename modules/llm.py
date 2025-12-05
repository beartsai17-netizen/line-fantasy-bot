# modules/llm.py
import os
from openai import OpenAI

# 這裡不需要再 load_dotenv，app.py 啟動時已經載入環境變數
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    raise Exception("缺少 OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)


def ask_bot_with_memory(user_question: str, memory_text: str) -> str:
    """
    使用群組記憶 + 使用者問題，向 OpenAI 發問並回傳回答文字。
    """
    system_prompt = (
        "你是一個友善的 LINE 群組助理。\n"
        "請在回答時參考以下群組近期聊天內容（如果有）：\n\n"
        f"{memory_text}\n"
        "——以上是群組背景——\n"
        "若背景與問題無關，可以只根據問題本身回答。"
    )

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question},
        ],
    )

    return res.choices[0].message.content

