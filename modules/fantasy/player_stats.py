# modules/fantasy/player_stats.py

"""
負責處理 Yahoo Fantasy API 回傳的原始資料，
例如：本季 stats、recent stats（7/14/30 天）、
統一格式化 stat。
"""

def get_season_stats(player_key):
    """從 app.py 的 yahoo_get_player_season_avg 呼叫"""
    from app import yahoo_get_player_season_avg
    return yahoo_get_player_season_avg(player_key)


def get_recent_stats(player_key, days):
    """從 app.py 的 yahoo_get_player_stats_by_date_range 呼叫"""
    from app import yahoo_get_player_stats_by_date_range
    return yahoo_get_player_stats_by_date_range(player_key, days)


def format_stats_for_llm(stats_dict):
    """將 Yahoo 回傳的 dict 整理為可讀文字（餵進 LLM）"""
    # 這裡先留空，之後我們會做格式化
    return str(stats_dict)
