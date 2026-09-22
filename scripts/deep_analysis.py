#!/usr/bin/env python3
"""
微信聊天深度分析引擎
====================
在 chat_analysis.py 基础上扩展 12 项深度分析：
 1. 总体概览 + 消息类型分布
 2. 趋势分析（日/周/月）
 3. 群聊活跃度 + 跨群活跃成员
 4. 私聊频次
 5. 沉寂联系人预警
 6. 未回复私聊预警
 7. 群话题热点提取
 8. 承诺与待办抓取
 9. 商机挖掘
10. 联系人画像
11. 群分类（工作/购物/家庭/社交/其他）
12. 全文检索（输出搜索用 JSON，供前端/脚本调用）

用法：
    python3 deep_analysis.py --msg-db <msg.db> --contact-db <contact.db> --my-wxid <wxid> \
        --start-date 2026-09-15 --end-date 2026-09-21 --output deep_result.json

依赖：pip install zstandard
"""

import sqlite3
import hashlib
import json
import datetime
import argparse
import os
import re
from collections import Counter, defaultdict

try:
    import zstandard
    dctx = zstandard.ZstdDecompressor()
except ImportError:
    dctx = None

# ===== 常量 =====

MSG_TYPES = {1: "文字", 3: "图片", 34: "语音", 42: "名片", 43: "视频",
             47: "表情包", 48: "位置", 50: "语音通话", 66: "微信运动",
             67: "文件", 10000: "系统消息"}

# 商机关键词（电信行业）
OPPORTUNITY_KEYWORDS = {
    "需求意向": ["需要", "想要", "打算", "计划", "准备", "考虑", "想办", "想装", "想用", "有意"],
    "产品咨询": ["宽带", "套餐", "号码", "FTTR", "5G", "专线", "电路", "云", "物联网",
                 "光纤", "千兆", "流量", "语音", "机", "卡", "融合", "全光", "组网"],
    "采购招标": ["采购", "招标", "询价", "报价", "预算", "合同", "签约", "中标", "投标", "集采", "选型"],
    "竞品线索": ["移动", "联通", "广电", "携号转网", "转网", "竞品", "异网", "友商", "友商的"],
    "合作意向": ["合作", "意向", "客户", "商机", "线索", "推荐", "介绍", "咨询", "了解一下"],
    "流失预警": ["取消", "退订", "不用了", "到期", "续费", "续约", "挽留", "投诉", "不满意"],
}

# 承诺/待办关键词
COMMITMENT_FIRST_PERSON = ["我来", "我去", "我会", "我负责", "我安排", "我处理",
                           "我跟", "我弄", "我看", "我查", "我问", "我催", "我发"]
COMMITMENT_TIME = ["今天", "明天", "后天", "本周", "下周", "稍后", "马上", "立刻",
                   "尽快", "一会", "等下", "下班前", "上午", "下午", "月底前"]
COMMITMENT_ACTION = ["处理", "回复", "确认", "跟进", "安排", "提交", "发送", "完成",
                     "交付", "上线", "解决", "协调", "对接", "核实", "整理", "汇总",
                     "反馈", "通知", "联系", "催", "报", "给"]

# 中文停用词（高频无意义词）
STOP_CHARS = set("的了是都有在就也和我你他她它们这那个个不没要会能可以一上下中为以对到把被让使给跟向从向由这那地得着过吗呢吧啊呀哦嗯啦呐呵哈嘿")

# 群分类关键词
GROUP_CLASSIFY_RULES = {
    "工作": ["工作", "项目", "部门", "组", "中心", "部", "市场", "经营", "分析",
             "行动", "专班", "群", "作战", "推进", "攻坚", "专项", "保障", "服务",
             "运营", "管理", "战略", "发展", "建设", "改革", "规划", "落实"],
    "购物": ["购", "券", "优惠", "折", "团", "买", "卖", "省钱", "薅", "好物", "种草"],
    "家庭": ["家", "亲", "爸妈", "父母", "兄弟", "姐妹", "亲戚", "家族"],
    "社交": ["朋友", "同学", "校友", "聚会", "聚餐", "运动", "健身", "游戏", "爱好"],
}


# ===== 数据库辅助 =====

def decompress_content(content, wcdb_ct):
    if wcdb_ct is None or wcdb_ct == 0:
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='replace')
        return content or ""
    if isinstance(content, bytes):
        try:
            return dctx.decompress(content).decode('utf-8', errors='replace')
        except Exception:
            return ""
    return content or ""


def build_name_map(contact_db):
    conn = sqlite3.connect(contact_db)
    name_map = {}
    for username, nick, remark in conn.execute(
        "SELECT username, nick_name, remark FROM contact WHERE delete_flag = 0"
    ).fetchall():
        name_map[username] = remark if remark else (nick if nick else username)
    conn.close()
    return name_map


def build_session_map(msg_db):
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    sessions = {}
    id2name = {}
    for username, is_session in cur.execute("SELECT user_name, is_session FROM Name2Id").fetchall():
        h = hashlib.md5(username.encode()).hexdigest()
        table = f"Msg_{h}"
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if cur.fetchone():
            sessions[username] = {'table': table, 'is_session': is_session}
    # 构建 rowid -> username 映射
    for rowid, username in cur.execute("SELECT rowid, user_name FROM Name2Id").fetchall():
        id2name[rowid] = username
    conn.close()
    return sessions, id2name


def parse_date_range(start_date, end_date):
    start_ts = end_ts = None
    if start_date:
        dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        start_ts = int(dt.replace(hour=0, minute=0, second=0).timestamp())
    if end_date:
        dt = datetime.datetime.strptime(end_date, '%Y-%m-%d')
        end_ts = int(dt.replace(hour=23, minute=59, second=59).timestamp())
    return start_ts, end_ts


def ts_to_str(ts):
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def ts_to_date(ts):
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


# ===== 关键词提取 =====

def extract_keywords(texts, top_n=15):
    """从文本列表中提取高频关键词（2-4字组合）"""
    if not texts:
        return []
    # 合并所有文本
    corpus = " ".join(texts)
    # 按标点和空格分句
    segments = re.split(r'[，。！？、；：\s\n\r\t【】()（）""''《》—…·.,!?;:\-]+', corpus)
    # 提取 2-4 字词组
    word_freq = Counter()
    for seg in segments:
        seg = seg.strip()
        if len(seg) < 2:
            continue
        # 直接取 2-4 字窗口
        for w_len in (2, 3, 4):
            for i in range(len(seg) - w_len + 1):
                word = seg[i:i+w_len]
                # 过滤停用词开头的
                if word[0] in STOP_CHARS or word[-1] in STOP_CHARS:
                    continue
                # 过滤纯数字/纯英文短词
                if word.isdigit():
                    continue
                word_freq[word] += 1
    # 去重：如果一个长词包含短词且频率相近，保留长词
    candidates = word_freq.most_common(top_n * 3)
    result = []
    seen = set()
    for word, freq in candidates:
        if freq < 2:
            continue
        # 检查是否被已选词包含
        skip = False
        for prev_word in seen:
            if word in prev_word and freq <= word_freq[prev_word] * 1.2:
                skip = True
                break
        if not skip:
            result.append({"keyword": word, "count": freq})
            seen.add(word)
        if len(result) >= top_n:
            break
    return result


# ===== 分析模块 =====

def analyze_overall(msg_db, sessions, start_ts, end_ts):
    """总体统计 + 消息类型分布"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    total = 0
    min_t, max_t = 9999999999, 0
    type_counter = Counter()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    for username, info in sessions.items():
        table = info['table']
        try:
            rows = cur.execute(
                f"SELECT local_type, COUNT(*), MIN(create_time), MAX(create_time) "
                f"FROM `{table}`{where} GROUP BY local_type", params
            ).fetchall()
            for lt, c, mn, mx in rows:
                total += c
                if mn and mn < min_t: min_t = mn
                if mx and mx > max_t: max_t = mx
                base = lt & 0xFF
                type_name = MSG_TYPES.get(lt) or MSG_TYPES.get(base, f"其他({lt})")
                type_counter[type_name] += c
        except:
            pass
    conn.close()

    chatroom_count = sum(1 for u in sessions if '@chatroom' in u)
    private_count = sum(1 for u in sessions if '@chatroom' not in u and '@openim' not in u)

    return {
        "total_messages": total,
        "total_chatrooms": chatroom_count,
        "total_private_chats": private_count,
        "time_range": [ts_to_str(min_t), ts_to_str(max_t)] if total else ["", ""],
        "type_breakdown": dict(type_counter.most_common()),
    }


def analyze_trend(msg_db, sessions, start_ts, end_ts):
    """日趋势 + 小时分布 + 星期分布"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    daily = defaultdict(int)
    hourly = [0] * 24
    weekday = [0] * 7
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    for username, info in sessions.items():
        try:
            for (ts,) in cur.execute(f"SELECT create_time FROM `{info['table']}`{where}", params):
                if not ts:
                    continue
                dt = datetime.datetime.fromtimestamp(ts)
                daily[dt.strftime('%Y-%m-%d')] += 1
                hourly[dt.hour] += 1
                weekday[dt.weekday()] += 1
        except:
            pass
    conn.close()

    wd_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    return {
        "daily": [{"date": d, "count": c} for d, c in sorted(daily.items())],
        "hourly": [{"hour": h, "count": hourly[h]} for h in range(24)],
        "weekday": [{"name": wd_names[i], "count": weekday[i]} for i in range(7)],
    }


def analyze_chatrooms(msg_db, sessions, name_map, start_ts, end_ts):
    """群聊活跃度 + 跨群活跃成员"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    chatroom_stats = []
    sender_counter = Counter()
    sender_chatrooms = defaultdict(Counter)

    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        try:
            total, mn, mx = cur.execute(
                f"SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`{where}", params
            ).fetchone()
            if total == 0:
                continue
            # 发送者统计（仅文字消息）
            text_rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content FROM `{table}`"
                f"{' WHERE local_type=1' + (' AND ' + ' AND '.join(conds) if conds else '')}",
                params
            ).fetchall()
            room_senders = Counter()
            for content, wct in text_rows:
                text = decompress_content(content, wct)
                if text and ':\n' in text:
                    sender = text.split(':\n', 1)[0]
                    room_senders[sender] += 1
                    sender_counter[sender] += 1
            display = name_map.get(username, username)
            for s, c in room_senders.items():
                sender_chatrooms[s][display] += c
            chatroom_stats.append({
                "name": display, "username": username,
                "message_count": total,
                "sender_count": len(room_senders),
                "top_senders": [{"name": name_map.get(s, s), "count": c}
                                for s, c in room_senders.most_common(5)],
            })
        except:
            pass
    conn.close()

    chatroom_stats.sort(key=lambda x: x['message_count'], reverse=True)

    top_senders = []
    for s, c in sender_counter.most_common(30):
        top_cr = sender_chatrooms[s].most_common(1)
        top_senders.append({
            "name": name_map.get(s, s), "count": c,
            "top_chatroom": top_cr[0][0] if top_cr else "",
            "top_chatroom_count": top_cr[0][1] if top_cr else 0,
        })

    return chatroom_stats, top_senders


def analyze_private_chats(msg_db, sessions, name_map, start_ts, end_ts):
    """私聊频次"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    private_stats = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        table = sessions[username]['table']
        try:
            total, mn, mx = cur.execute(
                f"SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`{where}", params
            ).fetchone()
            if total == 0:
                continue
            private_stats.append({
                "name": name_map.get(username, username),
                "username": username,
                "message_count": total,
                "last_time": ts_to_str(mx),
                "last_ts": mx,
            })
        except:
            pass
    conn.close()
    private_stats.sort(key=lambda x: x['message_count'], reverse=True)
    return private_stats


def analyze_dormant_contacts(msg_db, sessions, name_map, my_wxid, threshold_days=7):
    """沉寂联系人：超过 threshold_days 天没有私聊的联系人"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    now_ts = datetime.datetime.now().timestamp()
    dormant = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if username == my_wxid:
            continue
        table = sessions[username]['table']
        try:
            total, last_ts = cur.execute(
                f"SELECT COUNT(*), MAX(create_time) FROM `{table}`"
            ).fetchone()
            if total == 0 or not last_ts:
                continue
            days = (now_ts - last_ts) / 86400
            if days >= threshold_days:
                dormant.append({
                    "name": name_map.get(username, username),
                    "last_message_date": ts_to_date(last_ts),
                    "days_since": int(days),
                    "total_messages": total,
                })
        except:
            pass
    conn.close()
    dormant.sort(key=lambda x: x['days_since'], reverse=True)
    return dormant[:50]


def analyze_unreplied(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """未回复私聊：最后一条消息来自对方且超过一定时间"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    unreplied = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, local_type, create_time, real_sender_id "
                f"FROM `{table}` ORDER BY create_time DESC LIMIT 10"
            ).fetchall()
            if not rows:
                continue
            my_latest = None
            other_latest = None
            other_last_text = ""
            for content, wct, lt, ts, sender_id in rows:
                if lt == 10000:
                    continue
                is_mine = (sender_id == my_rowid)
                if is_mine:
                    if my_latest is None:
                        my_latest = ts
                else:
                    if other_latest is None:
                        other_latest = ts
                        other_last_text = decompress_content(content, wct)
            if other_latest and (my_latest is None or other_latest > my_latest):
                hours_ago = (datetime.datetime.now().timestamp() - other_latest) / 3600
                if hours_ago >= 2:
                    unreplied.append({
                        "name": name_map.get(username, username),
                        "last_message_time": ts_to_str(other_latest),
                        "hours_ago": round(hours_ago, 1),
                        "last_content": (other_last_text or "")[:100],
                    })
        except:
            pass
    conn.close()
    unreplied.sort(key=lambda x: x['hours_ago'], reverse=True)
    return unreplied[:20]


def analyze_group_topics(msg_db, sessions, name_map, start_ts, end_ts, top_groups=10):
    """群话题热点：提取每个活跃群的文本消息关键词"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    # 先找最活跃的群
    group_msgs = []
    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        try:
            total = cur.execute(
                f"SELECT COUNT(*) FROM `{table}`{where}", params
            ).fetchone()[0]
            if total > 0:
                group_msgs.append((username, table, total))
        except:
            pass
    group_msgs.sort(key=lambda x: x[2], reverse=True)

    topics = []
    for username, table, msg_count in group_msgs[:top_groups]:
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content FROM `{table}`{where}", params
            ).fetchall()
            texts = []
            for content, wct in rows:
                text = decompress_content(content, wct)
                if text and ':\n' in text:
                    text = text.split(':\n', 1)[1]  # 去掉发送者前缀
                if text and len(text) > 1:
                    texts.append(text)
            keywords = extract_keywords(texts, top_n=10)
            if keywords:
                topics.append({
                    "group": name_map.get(username, username),
                    "message_count": msg_count,
                    "keywords": keywords,
                })
        except:
            pass
    conn.close()
    return topics


def analyze_commitments(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """承诺与待办抓取"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    commitments = []
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id "
                f"FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 3:
                    continue
                # 群聊消息去掉发送者前缀
                sender_name = ""
                is_mine = (sender_id == my_rowid)
                if is_group and ':\n' in text:
                    sender_wxid, text = text.split(':\n', 1)
                    sender_name = name_map.get(sender_wxid, sender_wxid)
                    is_mine = (sender_wxid == id2name.get(my_rowid, ''))
                elif not is_group:
                    sender_name = "我" if is_mine else name_map.get(username, username)
                else:
                    sender_name = name_map.get(id2name.get(sender_id, ''), f"用户{sender_id}")

                # 匹配承诺模式
                has_first_person = any(p in text for p in COMMITMENT_FIRST_PERSON)
                has_time = any(p in text for p in COMMITMENT_TIME)
                has_action = any(p in text for p in COMMITMENT_ACTION)

                # 条件：(第一人称 AND 行动) OR (时间 AND 行动) OR (第一人称 AND 时间)
                if (has_first_person and has_action) or (has_time and has_action) or (has_first_person and has_time):
                    if len(text) > 200:
                        continue
                    commitments.append({
                        "sender": sender_name,
                        "content": text[:150],
                        "context": name_map.get(username, username),
                        "time": ts_to_str(ts),
                        "is_mine": is_mine,
                    })
        except:
            pass
    conn.close()
    commitments.sort(key=lambda x: x['time'], reverse=True)
    return commitments[:50]


def analyze_business_opportunities(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """商机挖掘"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    opportunities = []
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id "
                f"FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 3 or len(text) > 300:
                    continue
                is_mine = (sender_id == my_rowid)
                if is_group and ':\n' in text:
                    sender_wxid, text = text.split(':\n', 1)
                    sender_name = name_map.get(sender_wxid, sender_wxid)
                    is_mine = (sender_wxid == id2name.get(my_rowid, ''))
                else:
                    sender_name = "我" if is_mine else name_map.get(username, username)

                # 匹配商机关键词
                matched_types = []
                matched_keywords = []
                for opp_type, keywords in OPPORTUNITY_KEYWORDS.items():
                    hits = [kw for kw in keywords if kw in text]
                    if hits:
                        matched_types.append(opp_type)
                        matched_keywords.extend(hits)

                if matched_types:
                    opportunities.append({
                        "sender": sender_name,
                        "content": text[:200],
                        "context": name_map.get(username, username),
                        "time": ts_to_str(ts),
                        "opportunity_types": matched_types,
                        "keywords": list(set(matched_keywords)),
                        "is_mine": is_mine,
                    })
        except:
            pass
    conn.close()
    # 按时间倒序，优先展示竞品/采购类
    opportunities.sort(key=lambda x: x['time'], reverse=True)
    return opportunities[:80]


def analyze_contact_profiles(msg_db, sessions, name_map, my_wxid, top_n=20):
    """联系人画像：对最活跃的联系人生成画像"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    # 收集每个私聊联系人的统计
    profiles = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username or username == my_wxid:
            continue
        table = sessions[username]['table']
        try:
            total, first_ts, last_ts = cur.execute(
                f"SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`"
            ).fetchone()
            if total < 5:
                continue
            # 消息类型分布
            type_rows = cur.execute(
                f"SELECT local_type, COUNT(*) FROM `{table}` GROUP BY local_type ORDER BY COUNT(*) DESC LIMIT 5"
            ).fetchall()
            type_dist = {}
            for lt, c in type_rows:
                base = lt & 0xFF
                name = MSG_TYPES.get(lt) or MSG_TYPES.get(base, f"其他")
                type_dist[name] = c
            # 活跃天数
            days = max(1, (last_ts - first_ts) / 86400) if first_ts and last_ts else 1
            avg_daily = round(total / days, 1)
            profiles.append({
                "name": name_map.get(username, username),
                "total_messages": total,
                "first_contact": ts_to_date(first_ts),
                "last_contact": ts_to_date(last_ts),
                "active_days": int(days),
                "avg_daily": avg_daily,
                "type_breakdown": type_dist,
            })
        except:
            pass
    conn.close()
    profiles.sort(key=lambda x: x['total_messages'], reverse=True)
    return profiles[:top_n]


CATEGORY_MAP = {"工作": "work", "购物": "shopping", "家庭": "family", "社交": "social"}

def classify_groups(chatroom_stats):
    """群分类：根据群名关键词分类"""
    classified = {"work": [], "shopping": [], "family": [], "social": [], "other": []}
    for cr in chatroom_stats:
        name = cr['name']
        placed = False
        for cn_cat, keywords in GROUP_CLASSIFY_RULES.items():
            if any(kw in name for kw in keywords):
                en_cat = CATEGORY_MAP.get(cn_cat, "other")
                classified[en_cat].append({
                    "name": name, "message_count": cr['message_count'],
                    "sender_count": cr.get('sender_count', 0),
                })
                placed = True
                break
        if not placed:
            classified["other"].append({
                "name": name, "message_count": cr['message_count'],
                "sender_count": cr.get('sender_count', 0),
            })
    return classified


def full_text_search(msg_db, sessions, name_map, query, start_ts=None, end_ts=None, limit=50):
    """全文检索：在所有会话中搜索关键词"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    results = []
    for username, info in sessions.items():
        table = info['table']
        is_group = '@chatroom' in username
        try:
            conds = ["local_type = 1", "message_content LIKE ?"]
            params = [f"%{query}%"]
            if start_ts:
                conds.append("create_time >= ?"); params.append(start_ts)
            if end_ts:
                conds.append("create_time <= ?"); params.append(end_ts)
            where = " WHERE " + " AND ".join(conds)
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time "
                f"FROM `{table}`{where} ORDER BY create_time DESC LIMIT {limit}", params
            ).fetchall()
            for content, wct, ts in rows:
                text = decompress_content(content, wct)
                if not text or query not in text:
                    continue
                sender = ""
                if is_group and ':\n' in text:
                    sender_wxid, text = text.split(':\n', 1)
                    sender = name_map.get(sender_wxid, sender_wxid)
                results.append({
                    "session": name_map.get(username, username),
                    "sender": sender,
                    "content": text[:200],
                    "time": ts_to_str(ts),
                    "is_group": is_group,
                })
        except:
            pass
    conn.close()
    results.sort(key=lambda x: x['time'], reverse=True)
    return results[:limit]


# ===== 扩展分析模块（18项） =====

# --- 沟通质量类 ---

def analyze_response_time(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """响应时长分析：统计每个私聊联系人的平均回复耗时"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    results = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(
                f"SELECT create_time, real_sender_id, local_type FROM `{table}`{where} ORDER BY create_time ASC", params
            ).fetchall()
            if len(rows) < 4:
                continue
            # 计算回复耗时：连续两条消息发送者不同时，后一条距前一条的时间差
            my_reply_times = []   # 对方发→我回 的耗时
            their_reply_times = []  # 我发→对方回 的耗时
            prev_ts, prev_sender = None, None
            for ts, sender_id, lt in rows:
                if lt == 10000:
                    continue
                if prev_ts is not None and sender_id != prev_sender:
                    gap = ts - prev_ts
                    if gap < 86400 * 3:  # 排除超过3天的间隔（非连续对话）
                        if sender_id == my_rowid:
                            my_reply_times.append(gap)
                        else:
                            their_reply_times.append(gap)
                prev_ts, prev_sender = ts, sender_id

            def avg(lst):
                return round(sum(lst) / len(lst) / 60, 1) if lst else None  # 分钟

            my_avg = avg(my_reply_times)
            their_avg = avg(their_reply_times)
            if my_avg or their_avg:
                results.append({
                    "name": name_map.get(username, username),
                    "my_avg_reply_min": my_avg,
                    "their_avg_reply_min": their_avg,
                    "my_replies": len(my_reply_times),
                    "their_replies": len(their_reply_times),
                })
        except:
            pass
    conn.close()
    # 按对方回复耗时排序（慢的在前）
    results.sort(key=lambda x: x['their_avg_reply_min'] or 9999, reverse=True)
    return results[:30]


def analyze_relationship_temperature(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """关系温度计：每个私聊联系人的聊天频率趋势（升温/降温/稳定）"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    results = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            # 统计最近4周每周的消息量
            now_ts = end_ts or datetime.datetime.now().timestamp()
            weekly_counts = []
            for week_idx in range(4):
                w_end = now_ts - week_idx * 7 * 86400
                w_start = w_end - 7 * 86400
                count = cur.execute(
                    f"SELECT COUNT(*) FROM `{table}` WHERE create_time > ? AND create_time <= ?",
                    (w_start, w_end)
                ).fetchone()[0]
                weekly_counts.append(count)
            total = sum(weekly_counts)
            if total < 5:
                continue
            # 趋势判断：最近一周 vs 前三周平均
            recent = weekly_counts[0]
            earlier_avg = sum(weekly_counts[1:]) / 3 if any(weekly_counts[1:]) else 0
            if earlier_avg == 0:
                trend = "升温" if recent > 0 else "停滞"
            elif recent > earlier_avg * 1.3:
                trend = "升温"
            elif recent < earlier_avg * 0.7:
                trend = "降温"
            else:
                trend = "稳定"
            results.append({
                "name": name_map.get(username, username),
                "total_4w": total,
                "weekly_counts": weekly_counts,
                "trend": trend,
            })
        except:
            pass
    conn.close()
    # 降温的排前面
    trend_order = {"降温": 0, "升温": 1, "稳定": 2, "停滞": 3}
    results.sort(key=lambda x: (trend_order.get(x['trend'], 9), -x['total_4w']))
    return results[:30]


def analyze_best_contact_time(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """最佳联系时段：每个活跃私聊联系人最活跃的小时"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    results = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            conds = []
            params = []
            if start_ts:
                conds.append("create_time >= ?"); params.append(start_ts)
            if end_ts:
                conds.append("create_time <= ?"); params.append(end_ts)
            where = (" WHERE " + " AND ".join(conds)) if conds else ""
            rows = cur.execute(
                f"SELECT create_time, real_sender_id FROM `{table}`{where}", params
            ).fetchall()
            if len(rows) < 5:
                continue
            hour_counts = [0] * 24
            for ts, sender_id in rows:
                if sender_id != my_rowid:  # 对方发的消息
                    dt = datetime.datetime.fromtimestamp(ts)
                    hour_counts[dt.hour] += 1
            best_hour = max(range(24), key=lambda h: hour_counts[h])
            if hour_counts[best_hour] < 2:
                continue
            results.append({
                "name": name_map.get(username, username),
                "best_hour": best_hour,
                "best_hour_count": hour_counts[best_hour],
                "hourly_dist": [{"hour": h, "count": hour_counts[h]} for h in range(24) if hour_counts[h] > 0],
            })
        except:
            pass
    conn.close()
    results.sort(key=lambda x: x['best_hour_count'], reverse=True)
    return results[:20]


def analyze_conversation_direction(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """对话方向分析：我主动发起 vs 对方主动发起"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    results = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(
                f"SELECT create_time, real_sender_id FROM `{table}`{where} ORDER BY create_time ASC", params
            ).fetchall()
            if len(rows) < 5:
                continue
            # 统计对话发起次数：间隔>6小时算一次新的对话发起
            my_initiated = 0
            their_initiated = 0
            prev_ts = None
            for ts, sender_id in rows:
                if prev_ts is None or (ts - prev_ts) > 6 * 3600:
                    if sender_id == my_rowid:
                        my_initiated += 1
                    else:
                        their_initiated += 1
                prev_ts = ts
            total_init = my_initiated + their_initiated
            if total_init < 2:
                continue
            results.append({
                "name": name_map.get(username, username),
                "my_initiated": my_initiated,
                "their_initiated": their_initiated,
                "my_ratio": round(my_initiated / total_init * 100, 1),
                "their_ratio": round(their_initiated / total_init * 100, 1),
            })
        except:
            pass
    conn.close()
    results.sort(key=lambda x: x['my_initiated'] + x['their_initiated'], reverse=True)
    return results[:30]


# --- 内容智能类 ---

def analyze_repeated_questions(msg_db, sessions, name_map, start_ts, end_ts):
    """重复问题/痛点挖掘：在群聊中提取含问号的重复消息"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    # 收集所有群聊中含问号的消息
    question_pool = defaultdict(list)  # (群名, 关键词) -> [(sender, time, content)]
    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(f"SELECT message_content, WCDB_CT_message_content, create_time FROM `{table}`{where}", params).fetchall()
            for content, wct, ts in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 5 or len(text) > 200:
                    continue
                if ':\n' in text:
                    text = text.split(':\n', 1)[1]
                if '?' in text or '？' in text:
                    # 提取关键词做去重
                    keywords = tuple(sorted(extract_keywords([text], top_n=3)))
                    if keywords:
                        group_name = name_map.get(username, username)
                        key = (group_name, keywords)
                        question_pool[key].append({"content": text[:100], "time": ts_to_str(ts)})
        except:
            pass
    conn.close()

    # 找出现2次以上的
    repeated = []
    for (group, kws), items in question_pool.items():
        if len(items) >= 2:
            repeated.append({
                "group": group,
                "keywords": [k["keyword"] for k in extract_keywords([i["content"] for i in items], top_n=5)],
                "count": len(items),
                "sample": items[0]["content"],
                "first_time": items[0]["time"],
                "last_time": items[-1]["time"],
            })
    repeated.sort(key=lambda x: x['count'], reverse=True)
    return repeated[:20]


def analyze_link_sharing(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """链接/文章追踪：提取聊天中分享的链接"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    url_pattern = re.compile(r'https?://[^\s<>"\'，。！？、]+')
    links = []
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text:
                    continue
                if is_group and ':\n' in text:
                    text_body = text.split(':\n', 1)[1]
                else:
                    text_body = text
                urls = url_pattern.findall(text_body)
                if urls:
                    sender_name = "我" if sender_id == my_rowid else name_map.get(id2name.get(sender_id, ''), id2name.get(sender_id, ''))
                    links.append({
                        "url": urls[0][:200],
                        "sender": sender_name,
                        "context": name_map.get(username, username),
                        "time": ts_to_str(ts),
                        "is_group": is_group,
                    })
        except:
            pass
    conn.close()
    links.sort(key=lambda x: x['time'], reverse=True)
    return links[:50]


def analyze_file_flow(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """文件流转图谱：追踪文件消息的发送者"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    files = []
    file_exts = {'xlsx', 'xls', 'csv', 'docx', 'doc', 'pdf', 'ppt', 'pptx', 'zip', 'rar',
                 '7z', 'txt', 'md', 'json', 'html', 'apk', 'dmg', 'mp4', 'mov', 'mp3', 'wav'}
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 5:
                    continue
                text_body = text
                if is_group and ':\n' in text:
                    text_body = text.split(':\n', 1)[1]
                low = text_body.lower()
                for ext in file_exts:
                    if f'.{ext}' in low:
                        files.append({
                            "filename": text_body[:80],
                            "ext": ext,
                            "sender": "我" if sender_id == my_rowid else name_map.get(id2name.get(sender_id, ''), ''),
                            "context": name_map.get(username, username),
                            "is_group": is_group,
                            "time": ts_to_str(ts),
                        })
                        break
        except:
            pass
    conn.close()
    files.sort(key=lambda x: x['time'], reverse=True)
    return files[:50]


def analyze_meetings(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """会议/日程提取：从消息中提取会议时间、地点"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    # 会议关键词
    meeting_keywords = ["会议", "开会", "讨论", "碰头", "通知", "时间", "地点", "参加",
                        "会议室", "线上", "线下", "到场", "签到", "议程"]
    time_pattern = re.compile(r'(\d{1,2}月\d{1,2}日|\d{1,2}[:：]\d{2}|周[一二三四五六日天]|今天|明天|后天|上午|下午)')
    location_pattern = re.compile(r'(会议室|大厅|楼|室|号|路|街|大厦|中心|酒店|基地)')

    meetings = []
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 10 or len(text) > 300:
                    continue
                text_body = text
                if is_group and ':\n' in text:
                    text_body = text.split(':\n', 1)[1]
                # 必须同时包含会议关键词和时间信息
                has_meeting = any(kw in text_body for kw in meeting_keywords)
                has_time = time_pattern.search(text_body)
                if has_meeting and has_time:
                    sender_name = "我" if sender_id == my_rowid else name_map.get(id2name.get(sender_id, ''), '')
                    meetings.append({
                        "sender": sender_name,
                        "content": text_body[:150],
                        "context": name_map.get(username, username),
                        "time": ts_to_str(ts),
                    })
        except:
            pass
    conn.close()
    meetings.sort(key=lambda x: x['time'], reverse=True)
    return meetings[:30]


# --- 社交网络类 ---

def analyze_influence_map(msg_db, sessions, name_map, start_ts, end_ts):
    """影响力图谱：群里发言后最多人跟帖的人（话题引爆力）"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    # 统计每个人发言后5分钟内有多少不同的人跟帖
    influence = defaultdict(lambda: {"follow_ups": 0, "triggered_count": 0})
    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time FROM `{table}`{where}", params
            ).fetchall()
            msgs = []
            for content, wct, ts in rows:
                text = decompress_content(content, wct)
                if text and ':\n' in text:
                    sender = text.split(':\n', 1)[0]
                    msgs.append((sender, ts))
            msgs.sort(key=lambda x: x[1])
            for i, (sender, ts) in enumerate(msgs):
                # 统计5分钟内不同人跟帖
                follow_senders = set()
                for j in range(i + 1, min(i + 20, len(msgs))):
                    next_sender, next_ts = msgs[j]
                    if next_ts - ts > 300:  # 5分钟
                        break
                    if next_sender != sender:
                        follow_senders.add(next_sender)
                if follow_senders:
                    display = name_map.get(sender, sender)
                    influence[display]["follow_ups"] += len(follow_senders)
                    influence[display]["triggered_count"] += 1
        except:
            pass
    conn.close()

    result = []
    for name, data in influence.items():
        if data["triggered_count"] >= 2:
            result.append({
                "name": name,
                "follow_ups": data["follow_ups"],
                "triggered_count": data["triggered_count"],
                "avg_followers": round(data["follow_ups"] / data["triggered_count"], 1),
            })
    result.sort(key=lambda x: x['follow_ups'], reverse=True)
    return result[:20]


def analyze_bridge_persons(msg_db, sessions, name_map, start_ts, end_ts):
    """桥梁人物：跨多个群都活跃的人（信息中间人）"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    sender_groups = defaultdict(set)  # sender -> {group names}
    sender_msg_count = defaultdict(int)
    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        group_name = name_map.get(username, username)
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content FROM `{table}`{where}", params
            ).fetchall()
            for content, wct in rows:
                text = decompress_content(content, wct)
                if text and ':\n' in text:
                    sender = text.split(':\n', 1)[0]
                    sender_groups[sender].add(group_name)
                    sender_msg_count[sender] += 1
        except:
            pass
    conn.close()

    result = []
    for sender, groups in sender_groups.items():
        if len(groups) >= 3:  # 至少在3个群活跃
            result.append({
                "name": name_map.get(sender, sender),
                "group_count": len(groups),
                "groups": list(groups)[:10],
                "total_messages": sender_msg_count[sender],
            })
    result.sort(key=lambda x: x['group_count'], reverse=True)
    return result[:20]


def analyze_circle_discovery(msg_db, sessions, name_map, start_ts, end_ts):
    """圈子发现：经常一起出现在多个群的人自动聚类"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    # 构建 sender -> {groups} 映射
    sender_groups = defaultdict(set)
    group_senders = defaultdict(set)
    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        group_name = name_map.get(username, username)
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content FROM `{table}`{where}", params
            ).fetchall()
            for content, wct in rows:
                text = decompress_content(content, wct)
                if text and ':\n' in text:
                    sender = text.split(':\n', 1)[0]
                    sender_groups[sender].add(group_name)
                    group_senders[group_name].add(sender)
        except:
            pass
    conn.close()

    # 计算两个人共同出现的群数
    pair_overlap = Counter()
    for group, senders in group_senders.items():
        sender_list = list(senders)
        for i in range(len(sender_list)):
            for j in range(i + 1, len(sender_list)):
                pair_overlap[(sender_list[i], sender_list[j])] += 1

    # 聚类：共同出现在3+个群的人归为一个圈子
    circles = []
    used = set()
    for (s1, s2), overlap in pair_overlap.most_common(100):
        if overlap < 3:
            break
        if s1 in used and s2 in used:
            continue
        # 查找与这两个人都有高重叠的其他人
        circle_members = {s1, s2}
        for (p1, p2), ov in pair_overlap.items():
            if ov >= 3:
                if p1 in circle_members:
                    circle_members.add(p2)
                elif p2 in circle_members:
                    circle_members.add(p1)
        if len(circle_members) >= 3:
            member_names = [name_map.get(s, s) for s in circle_members if s not in used]
            if len(member_names) >= 3:
                common_groups = set.intersection(*[sender_groups[s] for s in circle_members if sender_groups.get(s)])
                circles.append({
                    "members": member_names[:10],
                    "member_count": len(member_names),
                    "common_groups": list(common_groups)[:5],
                    "overlap": overlap,
                })
                used.update(circle_members)

    circles.sort(key=lambda x: x['member_count'], reverse=True)
    return circles[:10]


# --- 风险类 ---

def analyze_sensitive_info(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """敏感信息检测：手机号、身份证号、密码、IP地址"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    patterns = {
        "手机号": re.compile(r'1[3-9]\d{9}'),
        "身份证号": re.compile(r'\d{17}[\dXx]'),
        "IP地址": re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'),
        "密码/口令": re.compile(r'(密码|口令|password|passwd|pwd)[：:\s]*[^\s，。]{4,}', re.I),
    }

    findings = []
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 5:
                    continue
                text_body = text
                if is_group and ':\n' in text:
                    text_body = text.split(':\n', 1)[1]
                for info_type, pattern in patterns.items():
                    matches = pattern.findall(text_body)
                    if matches:
                        sender_name = "我" if sender_id == my_rowid else name_map.get(id2name.get(sender_id, ''), '')
                        findings.append({
                            "type": info_type,
                            "match": matches[0][:30] if info_type != "密码/口令" else "[已隐藏]",
                            "sender": sender_name,
                            "context": name_map.get(username, username),
                            "time": ts_to_str(ts),
                        })
        except:
            pass
    conn.close()
    findings.sort(key=lambda x: x['time'], reverse=True)
    return findings[:30]


def analyze_anomaly(msg_db, sessions, name_map, id2name, my_rowid, end_ts):
    """异常行为预警：某人消息量暴增/暴跌"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    # 对比最近一周 vs 前一周
    if end_ts is None:
        end_ts = datetime.datetime.now().timestamp()
    recent_start = end_ts - 7 * 86400
    prev_start = end_ts - 14 * 86400
    prev_end = recent_start

    anomalies = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            recent_count = cur.execute(
                f"SELECT COUNT(*) FROM `{table}` WHERE create_time > ? AND create_time <= ?",
                (recent_start, end_ts)
            ).fetchone()[0]
            prev_count = cur.execute(
                f"SELECT COUNT(*) FROM `{table}` WHERE create_time > ? AND create_time <= ?",
                (prev_start, prev_end)
            ).fetchone()[0]
            if recent_count + prev_count < 5:
                continue
            if prev_count == 0 and recent_count >= 10:
                change = "暴增（从0到%d）" % recent_count
            elif prev_count == 0:
                continue
            else:
                ratio = recent_count / prev_count
                if ratio >= 3:
                    change = f"暴增({ratio:.1f}倍)"
                elif ratio <= 0.3:
                    change = f"暴跌({ratio:.1f}倍)"
                else:
                    continue
            anomalies.append({
                "name": name_map.get(username, username),
                "recent_count": recent_count,
                "prev_count": prev_count,
                "change": change,
            })
        except:
            pass
    conn.close()
    anomalies.sort(key=lambda x: abs(x['recent_count'] - x['prev_count']), reverse=True)
    return anomalies[:15]


def analyze_commitment_tracking(msg_db, sessions, name_map, id2name, my_rowid, end_ts):
    """承诺追踪：上期的承诺在本期是否被提及兑现"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    # 上期承诺（前7天）
    prev_end = end_ts - 7 * 86400 if end_ts else datetime.datetime.now().timestamp() - 7 * 86400
    prev_start = prev_end - 7 * 86400
    this_start = prev_end
    this_end = end_ts or datetime.datetime.now().timestamp()

    # 提取上期承诺
    prev_commitments = []
    for username in sessions:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id "
                f"FROM `{table}` WHERE create_time > ? AND create_time <= ? AND local_type = 1",
                (prev_start, prev_end)
            ).fetchall()
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text or len(text) < 3 or len(text) > 200:
                    continue
                text_body = text
                if is_group and ':\n' in text:
                    text_body = text.split(':\n', 1)[1]
                has_first = any(p in text_body for p in COMMITMENT_FIRST_PERSON)
                has_action = any(p in text_body for p in COMMITMENT_ACTION)
                if has_first and has_action:
                    prev_commitments.append({
                        "content": text_body[:100],
                        "context": name_map.get(username, username),
                    })
        except:
            pass

    # 检查本期是否有相关消息（简单关键词匹配）
    fulfilled = []
    for commit in prev_commitments[:50]:  # 限制数量
        keywords = [w for w in commit["content"].split() if len(w) >= 2]
        if not keywords:
            continue
        match_count = 0
        for username in sessions:
            table = sessions[username]['table']
            try:
                for kw in keywords[:3]:
                    rows = cur.execute(
                        f"SELECT COUNT(*) FROM `{table}` WHERE create_time > ? AND create_time <= ? AND local_type = 1 AND message_content LIKE ?",
                        (this_start, this_end, f"%{kw}%")
                    ).fetchone()
                    if rows[0] > 0:
                        match_count += 1
                        break
            except:
                pass
        if match_count > 0:
            fulfilled.append(commit)

    conn.close()
    return {
        "total_prev_commitments": len(prev_commitments),
        "fulfilled": fulfilled[:20],
        "untracked": len(prev_commitments) - len(fulfilled),
    }


# --- 效率类 ---

def analyze_voice_ratio(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """语音消息占比榜：谁最爱发语音"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    sender_stats = defaultdict(lambda: {"total": 0, "voice": 0})
    for username in sessions:
        if '@chatroom' not in username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, local_type FROM `{table}`{where}", params
            ).fetchall()
            for content, wct, lt in rows:
                text = decompress_content(content, wct)
                sender = None
                if text and ':\n' in text:
                    sender = text.split(':\n', 1)[0]
                if not sender:
                    continue
                base = lt & 0xFF
                sender_stats[sender]["total"] += 1
                if lt == 34 or base == 34:
                    sender_stats[sender]["voice"] += 1
        except:
            pass
    conn.close()

    result = []
    for sender, stats in sender_stats.items():
        if stats["total"] >= 5 and stats["voice"] > 0:
            result.append({
                "name": name_map.get(sender, sender),
                "total": stats["total"],
                "voice": stats["voice"],
                "voice_ratio": round(stats["voice"] / stats["total"] * 100, 1),
            })
    result.sort(key=lambda x: x['voice_ratio'], reverse=True)
    return result[:20]


def analyze_late_night_contacts(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts):
    """深夜沟通对象：23-5点和谁在聊"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds, params = [], []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    night_contacts = defaultdict(int)
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            rows = cur.execute(
                f"SELECT create_time, real_sender_id FROM `{table}`{where}", params
            ).fetchall()
            for ts, sender_id in rows:
                dt = datetime.datetime.fromtimestamp(ts)
                if dt.hour >= 23 or dt.hour <= 5:
                    night_contacts[name_map.get(username, username)] += 1
        except:
            pass
    conn.close()

    result = [{"name": name, "count": count} for name, count in night_contacts.items()]
    result.sort(key=lambda x: x['count'], reverse=True)
    return result[:15]


def analyze_one_time_contacts(msg_db, sessions, name_map, id2name, my_rowid):
    """一次性联系人：只聊过几天就再也没联系的人"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    now_ts = datetime.datetime.now().timestamp()
    results = []
    for username in sessions:
        if '@chatroom' in username or '@openim' in username:
            continue
        if id2name.get(my_rowid) == username:
            continue
        table = sessions[username]['table']
        try:
            total, first_ts, last_ts = cur.execute(
                f"SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`"
            ).fetchone()
            if total < 3 or not first_ts or not last_ts:
                continue
            active_days = (last_ts - first_ts) / 86400
            days_since = (now_ts - last_ts) / 86400
            # 活跃期<3天且距今>14天
            if active_days < 3 and days_since > 14:
                results.append({
                    "name": name_map.get(username, username),
                    "total_messages": total,
                    "active_days": round(active_days, 1),
                    "last_contact": ts_to_date(last_ts),
                    "days_since": int(days_since),
                })
        except:
            pass
    conn.close()
    results.sort(key=lambda x: x['days_since'], reverse=True)
    return results[:20]


# ===== 主函数 =====

def main():
    parser = argparse.ArgumentParser(description="微信聊天深度分析引擎")
    parser.add_argument("--msg-db", required=True, help="解密后的消息数据库路径")
    parser.add_argument("--contact-db", required=True, help="解密后的联系人数据库路径")
    parser.add_argument("--my-wxid", required=True, help="自己的 wxid")
    parser.add_argument("--start-date", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--search", default=None, help="全文检索关键词（可选）")
    args = parser.parse_args()

    msg_db = os.path.expanduser(args.msg_db)
    contact_db = os.path.expanduser(args.contact_db)
    output = os.path.expanduser(args.output)

    start_ts, end_ts = parse_date_range(args.start_date, args.end_date)

    print("=== 微信聊天深度分析 ===")
    print(f"统计范围: {args.start_date or '最早'} ~ {args.end_date or '最近'}")

    # 构建映射
    print("构建联系人映射...")
    name_map = build_name_map(contact_db)
    print(f"  联系人: {len(name_map)}")

    print("构建会话映射...")
    sessions, id2name = build_session_map(msg_db)
    print(f"  会话: {len(sessions)}")
    # 找到自己的 rowid
    my_rowid = None
    for rid, uname in id2name.items():
        if uname == args.my_wxid:
            my_rowid = rid
            break
    print(f"  我的 rowid: {my_rowid} ({args.my_wxid})")

    # 1. 总体概览
    print("分析总体统计...")
    overall = analyze_overall(msg_db, sessions, start_ts, end_ts)
    print(f"  总消息: {overall['total_messages']}")

    # 2. 趋势分析
    print("分析趋势...")
    trend = analyze_trend(msg_db, sessions, start_ts, end_ts)

    # 3. 群聊分析
    print("分析群聊活跃度...")
    chatroom_stats, top_senders = analyze_chatrooms(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  活跃群聊: {len(chatroom_stats)}")

    # 4. 私聊分析
    print("分析私聊频次...")
    private_stats = analyze_private_chats(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  活跃私聊: {len(private_stats)}")

    # 5. 沉寂联系人
    print("分析沉寂联系人...")
    dormant = analyze_dormant_contacts(msg_db, sessions, name_map, args.my_wxid, threshold_days=7)
    print(f"  沉寂联系人: {len(dormant)}")

    # 6. 未回复私聊
    print("分析未回复私聊...")
    unreplied = analyze_unreplied(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  未回复: {len(unreplied)}")

    # 7. 群话题热点
    print("提取群话题热点...")
    group_topics = analyze_group_topics(msg_db, sessions, name_map, start_ts, end_ts, top_groups=10)
    print(f"  群话题: {len(group_topics)} 个群")

    # 8. 承诺与待办
    print("抓取承诺与待办...")
    commitments = analyze_commitments(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  承诺/待办: {len(commitments)} 条")

    # 9. 商机挖掘
    print("挖掘商机...")
    opportunities = analyze_business_opportunities(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  商机线索: {len(opportunities)} 条")

    # 10. 联系人画像
    print("生成联系人画像...")
    contact_profiles = analyze_contact_profiles(msg_db, sessions, name_map, args.my_wxid, top_n=20)
    print(f"  联系人画像: {len(contact_profiles)} 个")

    # 11. 群分类
    print("群分类...")
    group_classification = classify_groups(chatroom_stats)
    for cat, groups in group_classification.items():
        print(f"  {cat}: {len(groups)} 个群")

    # 12. 全文检索（可选）
    search_results = None
    if args.search:
        print(f"全文检索: '{args.search}'...")
        search_results = full_text_search(msg_db, sessions, name_map, args.search, start_ts, end_ts)
        print(f"  搜索结果: {len(search_results)} 条")

    # === 扩展分析（18项）===

    # 13. 响应时长分析
    print("分析响应时长...")
    response_times = analyze_response_time(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  响应时长: {len(response_times)} 人")

    # 14. 关系温度计
    print("分析关系温度...")
    relationship = analyze_relationship_temperature(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  关系温度: {len(relationship)} 人")

    # 15. 最佳联系时段
    print("分析最佳联系时段...")
    best_times = analyze_best_contact_time(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  最佳时段: {len(best_times)} 人")

    # 16. 对话方向分析
    print("分析对话方向...")
    directions = analyze_conversation_direction(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  对话方向: {len(directions)} 人")

    # 17. 重复问题/痛点挖掘
    print("挖掘重复问题...")
    repeated_q = analyze_repeated_questions(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  重复问题: {len(repeated_q)} 个")

    # 18. 链接/文章追踪
    print("追踪链接分享...")
    links = analyze_link_sharing(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  链接: {len(links)} 条")

    # 19. 文件流转图谱
    print("追踪文件流转...")
    files = analyze_file_flow(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  文件: {len(files)} 个")

    # 20. 会议/日程提取
    print("提取会议日程...")
    meetings = analyze_meetings(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  会议: {len(meetings)} 条")

    # 21. 影响力图谱
    print("分析影响力图谱...")
    influence = analyze_influence_map(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  影响力: {len(influence)} 人")

    # 22. 桥梁人物
    print("分析桥梁人物...")
    bridges = analyze_bridge_persons(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  桥梁: {len(bridges)} 人")

    # 23. 圈子发现
    print("发现社交圈子...")
    circles = analyze_circle_discovery(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  圈子: {len(circles)} 个")

    # 24. 敏感信息检测
    print("检测敏感信息...")
    sensitive = analyze_sensitive_info(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  敏感信息: {len(sensitive)} 条")

    # 25. 异常行为预警
    print("分析异常行为...")
    anomalies = analyze_anomaly(msg_db, sessions, name_map, id2name, my_rowid, end_ts)
    print(f"  异常: {len(anomalies)} 人")

    # 26. 承诺追踪
    print("追踪承诺兑现...")
    commitment_track = analyze_commitment_tracking(msg_db, sessions, name_map, id2name, my_rowid, end_ts)
    print(f"  上期承诺: {commitment_track['total_prev_commitments']}条, 疑似兑现: {len(commitment_track['fulfilled'])}条")

    # 27. 语音消息占比榜
    print("分析语音占比...")
    voice_ratios = analyze_voice_ratio(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  语音用户: {len(voice_ratios)} 人")

    # 28. 深夜沟通对象
    print("分析深夜沟通...")
    night_contacts = analyze_late_night_contacts(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts)
    print(f"  深夜联系: {len(night_contacts)} 人")

    # 29. 一次性联系人
    print("分析一次性联系人...")
    one_time = analyze_one_time_contacts(msg_db, sessions, name_map, id2name, my_rowid)
    print(f"  一次性: {len(one_time)} 人")

    # 汇总
    result = {
        "generated_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "date_range": [args.start_date or "", args.end_date or ""],
        "overall": overall,
        "trend": trend,
        "chatrooms": chatroom_stats[:30],
        "private_chats": private_stats[:30],
        "top_senders": top_senders[:20],
        "dormant_contacts": dormant,
        "unreplied_chats": unreplied,
        "group_topics": group_topics,
        "commitments": commitments,
        "business_opportunities": opportunities,
        "contact_profiles": contact_profiles,
        "group_classification": group_classification,
        # 扩展分析
        "response_times": response_times,
        "relationship_temperature": relationship,
        "best_contact_times": best_times,
        "conversation_directions": directions,
        "repeated_questions": repeated_q,
        "link_sharing": links,
        "file_flow": files,
        "meetings": meetings,
        "influence_map": influence,
        "bridge_persons": bridges,
        "circle_discovery": circles,
        "sensitive_info": sensitive,
        "anomaly_detection": anomalies,
        "commitment_tracking": commitment_track,
        "voice_ratio": voice_ratios,
        "late_night_contacts": night_contacts,
        "one_time_contacts": one_time,
    }
    if search_results is not None:
        result["search_results"] = {"query": args.search, "results": search_results}

    with open(output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n深度分析完成，结果已保存: {output}")


if __name__ == '__main__':
    main()
