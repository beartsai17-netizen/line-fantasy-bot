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

def analyze_value(player_name, season_text, last14_text, injury_text):
    """LLM：球員價值分析（Buy / Sell / Hold）"""
    prompt = f"""
請以 Yahoo Fantasy 的角度分析球員「{player_name}」的價值。

以下是他的資料：

【本季場均數據】
{season_text}

【最近 14 天的場均表現】
{last14_text}

【傷病狀況】
{injury_text}

請從以下方向進行分析：
1. 本季 baseline：他在該類別的期待值，是否高於/低於平均？
2. 兩週趨勢：是否呈現上升或下滑？哪些類別變強/變弱？
3. Regression 推估：過度波動 or 回到正常？
4. 角色與上場時間：有無起伏風險？
5. 傷病風險：是否會影響後續價值？
6. 給出最終結論：Buy Low / Sell High / Hold 中的其中一個。

輸出格式請簡潔、有層次，並提供 Fantasy 玩家可直接採用的建議。
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content

def compare_players(nameA, textA, nameB, textB):
    """LLM：比較兩位球員"""

    prompt = f"""
你是一位 Yahoo Fantasy 專業分析師，請比較兩位球員：

球員 A：{nameA}
數據：
{textA}

球員 B：{nameB}
數據：
{textB}

請依照以下面向分析：

1. 類別強弱（PTS / REB / AST / STL / BLK / TO / FG% / FT% / 3PM）
2. 使用率 (usage) 與角色穩定性
3. Regression 風險（過高表現是否會回落）
4. 傷病風險
5. 適合不同類型隊伍的原因
6. 最終給出簡潔結論（誰更適合大多數 Fantasy 玩家）

請用條列式、清楚分段的方式回答。
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

def evaluate_trade(nameA, textA, nameB, textB):
    """LLM：判斷 Fantasy 交易好壞（A 換 B）"""

    prompt = f"""
你是一位 Yahoo Fantasy 專業分析師，請分析以下 1-for-1 交易是否合理：

【玩家 A】
{nameA}
數據：
{textA}

【玩家 B】
{nameB}
數據：
{textB}

請從以下面向評估：
1. 類別價值變化（PTS / REB / AST / STL / BLK / 3PM / FG% / FT% / TO）
2. 本季 baseline 與 role 穩定性
3. 最近 14 天趨勢（上升 / 下滑）
4. 傷病風險
5. Regression 可能性（是否在 overperform / underperform）
6. 隊伍 fit：不同類型隊伍是否因這筆交易變強或變弱
7. 最終評價：
   - 大賺
   - 小賺
   - 合理
   - 小虧
   - 大虧

請清楚分段，產出專業 Fantasy 結論。
"""

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

