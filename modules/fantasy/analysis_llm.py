# modules/fantasy/analysis_llm.py

"""
使用 LLM 對 Fantasy stats 進行分析（不抓 API）
功能：!last14, !value, !vs, !trade
"""

from modules.llm import client


def analyze_last14(player_name, stats_14d_text):
    """LLM：分析最近 14 天趨勢"""
    prompt = f"""
請分析球員 {player_name} 在 Yahoo Fantasy 的最近 14 天表現。

以下是他最近 14 天的累積數據（已除以場次）：

{stats_14d_text}

請回答：
- 他在哪些數據變強？
- 哪些變弱？
- 是否回到應有水平？
- 對 Fantasy 玩家意味著什麼？
- 是否建議 Buy / Hold / Sell？
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content



def analyze_value(player_name, season_text, last14_text, injury_text):
    """LLM：球員價值 Buy Low / Sell High / 穩定"""
    prompt = f"""
請分析球員 {player_name} 的 fantasy 價值。

本季資料：
{season_text}

最近 14 天資料：
{last14_text}

傷病狀態：
{injury_text}

請回答此球員目前的價值、強勢與弱點，以及是否 Buy low / Sell high。
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content


def compare_players(nameA, textA, nameB, textB):
    """LLM：比較兩位球員"""

    prompt = f"""
請比較兩位球員在 fantasy 中的整體表現：

{nameA} 數據：
{textA}

{nameB} 數據：
{textB}

請依照：
- 類別強弱（PTS/REB/AST/STL/BLK/TO）
- 命中率
- 健康與角色穩定性
- 長期價值

給出結論。
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content


def evaluate_trade(nameA, textA, nameB, textB):
    """LLM：判斷交易好壞"""

    prompt = f"""
請判斷 Fantasy 交易是否合理：

玩家 A: {nameA}
數據：
{textA}

玩家 B: {nameB}
數據：
{textB}

請依照以下項目評估：
- 類別價值變化
- 健康風險
- 使用傾向 & regression
- 長期 fit
並標示：大賺 / 小賺 / 合理 / 小虧 / 大虧
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content
