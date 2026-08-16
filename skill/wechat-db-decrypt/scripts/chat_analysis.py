#!/usr/bin/env python3
"""
微信聊天数据分析脚本
====================
从解密后的message_0.db中分析聊天数据：
- 群聊活跃度排名（含群内最活跃发送者）
- 跨群聊最活跃的人（附带其最活跃的群名）
- 私聊频次排名
- 消息时间分布（小时/星期/月份/日趋势）
- 消息类型统计

支持WCDB zstd压缩消息的自动解压。

用法：
    python3 chat_analysis.py --msg-db <msg.db路径> --contact-db <contact.db路径> --my-wxid <你的wxid>

示例：
    python3 chat_analysis.py \
        --msg-db ./decrypted_db/message/message_0.db \
        --contact-db ./contact.db \
        --my-wxid your_wxid \
        --output ./analysis_result.json

日期过滤（可选）：
    --start-date 2026-08-15  --end-date 2026-08-15  # 只统计指定日期范围（含两端）
    不传日期参数时统计全量数据，保持向后兼容。

依赖：
    pip install zstandard
"""

import sqlite3
import hashlib
import json
import datetime
import argparse
import os
import zstandard
from collections import Counter, defaultdict

# 消息类型映射
MSG_TYPES = {
    1: "文字",
    3: "图片",
    34: "语音",
    42: "名片",
    43: "视频",
    47: "表情包",
    48: "位置",
    50: "语音通话",
    66: "微信运动",
    67: "文件",
    10000: "系统消息",
}

# zstd解压器
dctx = zstandard.ZstdDecompressor()


def parse_date_range(start_date, end_date):
    """解析日期范围，返回 (start_ts, end_ts) Unix 时间戳（含两端，含整天）"""
    start_ts = None
    end_ts = None
    if start_date:
        dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        start_ts = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    if end_date:
        dt = datetime.datetime.strptime(end_date, '%Y-%m-%d')
        end_ts = int(dt.replace(hour=23, minute=59, second=59, microsecond=0).timestamp())
    return start_ts, end_ts


def date_filter(start_ts, end_ts):
    """根据时间范围生成 (条件列表, 参数列表)，便于拼接 SQL WHERE 子句"""
    conds, params = [], []
    if start_ts is not None:
        conds.append("create_time >= ?")
        params.append(start_ts)
    if end_ts is not None:
        conds.append("create_time <= ?")
        params.append(end_ts)
    return conds, params


def decompress_content(content, wcdb_ct):
    """解压WCDB压缩的消息内容"""
    if wcdb_ct is None or wcdb_ct == 0:
        # 未压缩
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='replace')
        return content or ""

    # 压缩消息
    if isinstance(content, bytes):
        try:
            decompressed = dctx.decompress(content)
            return decompressed.decode('utf-8', errors='replace')
        except Exception:
            return "[压缩消息-解压失败]"
    return content or ""


def get_msg_type_name(local_type):
    """获取消息类型名称"""
    if local_type in MSG_TYPES:
        return MSG_TYPES[local_type]
    # 高位类型提取基础类型
    base_type = local_type & 0xFF
    if base_type in MSG_TYPES:
        return MSG_TYPES[base_type]
    return f"其他({local_type})"


def build_name_map(contact_db):
    """从contact.db构建 username -> display_name 映射
    
    昵称优先级：备注 > 昵称 > username
    """
    conn = sqlite3.connect(contact_db)
    cur = conn.cursor()

    name_map = {}
    cur.execute("SELECT username, local_type, nick_name, remark FROM contact WHERE delete_flag = 0")
    for username, ltype, nick, remark in cur.fetchall():
        display = remark if remark else (nick if nick else username)
        name_map[username] = display

    conn.close()
    return name_map


def build_session_map(msg_db):
    """构建 username -> {table_name, is_session} 映射
    
    微信4.x中，每个聊天对象的消息存在 Msg_<md5(username)> 表中。
    Name2Id表记录了所有username及其是否为活跃会话。
    """
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    sessions = {}
    cur.execute("SELECT user_name, is_session FROM Name2Id")
    for username, is_session in cur.fetchall():
        h = hashlib.md5(username.encode()).hexdigest()
        table_name = f"Msg_{h}"
        # 验证表是否实际存在
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if cur.fetchone():
            sessions[username] = {'table': table_name, 'is_session': is_session}

    conn.close()
    return sessions


def analyze_chatrooms(msg_db, sessions, name_map, start_ts=None, end_ts=None):
    """分析群聊活跃度
    
    返回:
        chatroom_stats: 每个群聊的详细统计
        sender_counter: 跨所有群聊的发送者消息计数
        sender_chatrooms: 每个发送者在各群的消息数，用于找最活跃的群
    """
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    # 群聊username列表
    chatroom_users = [u for u in sessions if '@chatroom' in u]

    chatroom_stats = []
    sender_counter = Counter()
    # 每个发送者 -> {群名: 消息数} 的映射
    sender_chatrooms = defaultdict(lambda: Counter())

    # 日期过滤条件
    conds, params = date_filter(start_ts, end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    for username in chatroom_users:
        table = sessions[username]['table']
        try:
            cur.execute(f"SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`{where}", params)
            total, min_time, max_time = cur.fetchone()
            if total == 0:
                continue

            # 统计各类型消息数
            cur.execute(f"SELECT local_type, COUNT(*) FROM `{table}`{where} GROUP BY local_type ORDER BY COUNT(*) DESC", params)
            type_counts = {get_msg_type_name(lt): c for lt, c in cur.fetchall()}

            # 统计群内发送者（仅文字消息，从content提取wxid）
            # 群聊消息格式: "wxid_xxx:\n实际内容"
            sender_conds = ["local_type = 1"] + conds
            sender_where = (" WHERE " + " AND ".join(sender_conds)) if sender_conds else ""
            cur.execute(f"""
                SELECT message_content, WCDB_CT_message_content 
                FROM `{table}`{sender_where}
            """, params)
            room_senders = Counter()
            for content, wcdb_ct in cur.fetchall():
                text = decompress_content(content, wcdb_ct)
                if ':\n' in text:
                    sender = text.split(':\n', 1)[0]
                    room_senders[sender] += 1
                    sender_counter[sender] += 1

            display_name = name_map.get(username, username)
            # 记录每个发送者在本群的消息数
            for sender, cnt in room_senders.items():
                sender_chatrooms[sender][display_name] += cnt

            chatroom_stats.append({
                'username': username,
                'name': display_name,
                'message_count': total,
                'time_range': [
                    datetime.datetime.fromtimestamp(min_time).strftime('%Y-%m-%d'),
                    datetime.datetime.fromtimestamp(max_time).strftime('%Y-%m-%d')
                ],
                'type_breakdown': type_counts,
                'top_senders': [
                    {'name': name_map.get(s, s), 'username': s, 'count': c}
                    for s, c in room_senders.most_common(10)
                ],
                'sender_count': len(room_senders)
            })
        except Exception as e:
            pass

    conn.close()

    chatroom_stats.sort(key=lambda x: x['message_count'], reverse=True)

    return chatroom_stats, sender_counter, sender_chatrooms


def analyze_private_chats(msg_db, sessions, name_map, start_ts=None, end_ts=None):
    """分析私聊频次
    
    私聊username不含@chatroom和@openim。
    """
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    private_users = [u for u in sessions if '@chatroom' not in u and '@openim' not in u]

    private_stats = []

    # 日期过滤条件
    conds, params = date_filter(start_ts, end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    for username in private_users:
        table = sessions[username]['table']
        try:
            cur.execute(f"SELECT COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`{where}", params)
            total, min_time, max_time = cur.fetchone()
            if total == 0:
                continue

            cur.execute(f"SELECT local_type, COUNT(*) FROM `{table}`{where} GROUP BY local_type ORDER BY COUNT(*) DESC", params)
            type_counts = {get_msg_type_name(lt): c for lt, c in cur.fetchall()}

            display_name = name_map.get(username, username)
            private_stats.append({
                'username': username,
                'name': display_name,
                'message_count': total,
                'time_range': [
                    datetime.datetime.fromtimestamp(min_time).strftime('%Y-%m-%d'),
                    datetime.datetime.fromtimestamp(max_time).strftime('%Y-%m-%d')
                ],
                'type_breakdown': type_counts
            })
        except Exception as e:
            pass

    conn.close()

    private_stats.sort(key=lambda x: x['message_count'], reverse=True)

    return private_stats


def analyze_time_distribution(msg_db, sessions, start_ts=None, end_ts=None):
    """分析消息时间分布：小时、星期、月份、日"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    hour_dist = [0] * 24
    weekday_dist = [0] * 7  # 0=周一...6=周日
    monthly_dist = defaultdict(int)
    daily_dist = defaultdict(int)

    # 日期过滤条件
    conds, params = date_filter(start_ts, end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    for username, info in sessions.items():
        table = info['table']
        try:
            cur.execute(f"SELECT create_time FROM `{table}`{where}", params)
            for (ts,) in cur.fetchall():
                if ts:
                    dt = datetime.datetime.fromtimestamp(ts)
                    hour_dist[dt.hour] += 1
                    weekday_dist[dt.weekday()] += 1
                    monthly_dist[dt.strftime('%Y-%m')] += 1
                    daily_dist[dt.strftime('%Y-%m-%d')] += 1
        except:
            pass

    conn.close()

    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday_result = [{'name': weekday_names[i], 'count': weekday_dist[i]} for i in range(7)]

    return {
        'hourly': [{'hour': h, 'count': hour_dist[h]} for h in range(24)],
        'weekly': weekday_result,
        'monthly': [{'month': m, 'count': c} for m, c in sorted(monthly_dist.items())],
        'daily': [{'date': d, 'count': c} for d, c in sorted(daily_dist.items())]
    }


def analyze_overall(msg_db, sessions, start_ts=None, end_ts=None):
    """总体统计：总消息数、群聊数、私聊数、时间范围、类型分布"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()

    total_messages = 0
    total_chatrooms = sum(1 for u in sessions if '@chatroom' in u)
    total_private = sum(1 for u in sessions if '@chatroom' not in u and '@openim' not in u)

    all_types = Counter()
    min_time = 9999999999
    max_time = 0

    # 日期过滤条件
    conds, params = date_filter(start_ts, end_ts)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""

    for username, info in sessions.items():
        table = info['table']
        try:
            cur.execute(f"SELECT local_type, COUNT(*), MIN(create_time), MAX(create_time) FROM `{table}`{where} GROUP BY local_type", params)
            for lt, c, mn, mx in cur.fetchall():
                total_messages += c
                all_types[get_msg_type_name(lt)] += c
                if mn and mn < min_time:
                    min_time = mn
                if mx and mx > max_time:
                    max_time = mx
        except:
            pass

    conn.close()

    return {
        'total_messages': total_messages,
        'total_chatrooms': total_chatrooms,
        'total_private_chats': total_private,
        'time_range': [
            datetime.datetime.fromtimestamp(min_time).strftime('%Y-%m-%d %H:%M'),
            datetime.datetime.fromtimestamp(max_time).strftime('%Y-%m-%d %H:%M')
        ],
        'type_breakdown': dict(all_types.most_common())
    }


def main():
    parser = argparse.ArgumentParser(description="微信聊天数据分析脚本")
    parser.add_argument("--msg-db", required=True, help="解密后的message_0.db路径")
    parser.add_argument("--contact-db", required=True, help="contact.db路径（联系人映射）")
    parser.add_argument("--my-wxid", required=True, help="你自己的wxid（用于排除自己）")
    parser.add_argument("--output", default="analysis_result.json", help="输出JSON文件路径")
    parser.add_argument("--start-date", default=None, help="起始日期 YYYY-MM-DD（可选，过滤统计范围）")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD（可选，过滤统计范围）")
    args = parser.parse_args()

    msg_db = os.path.expanduser(args.msg_db)
    contact_db = os.path.expanduser(args.contact_db)
    output_json = os.path.expanduser(args.output)

    print("=== 微信聊天分析 ===")
    print(f"数据源: {msg_db}")
    print(f"联系人映射: {contact_db}")
    if args.start_date or args.end_date:
        print(f"统计范围: {args.start_date or '最早'} ~ {args.end_date or '最近'}")
    print()

    # 解析日期范围
    start_ts, end_ts = parse_date_range(args.start_date, args.end_date)

    # 1. 构建映射
    print("构建联系人映射...")
    name_map = build_name_map(contact_db)
    print(f"  联系人: {len(name_map)}")

    print("构建会话映射...")
    sessions = build_session_map(msg_db)
    print(f"  会话: {len(sessions)} (群聊{sum(1 for u in sessions if '@chatroom' in u)}, 私聊{sum(1 for u in sessions if '@chatroom' not in u and '@openim' not in u)})")

    # 2. 总体统计
    print("\n计算总体统计...")
    overall = analyze_overall(msg_db, sessions, start_ts, end_ts)
    print(f"  总消息: {overall['total_messages']}")
    print(f"  时间范围: {overall['time_range'][0]} ~ {overall['time_range'][1]}")

    # 3. 群聊分析
    print("\n分析群聊活跃度...")
    chatroom_stats, sender_counter, sender_chatrooms = analyze_chatrooms(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  群聊数: {len(chatroom_stats)}")
    print(f"  Top 3群聊:")
    for c in chatroom_stats[:3]:
        print(f"    {c['name']}: {c['message_count']}条消息, {c['sender_count']}人发言")

    # 跨群聊最活跃的人（附带最活跃的群）
    top_senders_overall = []
    for s, c in sender_counter.most_common(30):
        if s == args.my_wxid:  # 排除自己
            continue
        top_chatroom = sender_chatrooms[s].most_common(1)
        chatroom_name = top_chatroom[0][0] if top_chatroom else '未知'
        chatroom_count = top_chatroom[0][1] if top_chatroom else 0
        top_senders_overall.append({
            'name': name_map.get(s, s),
            'username': s,
            'count': c,
            'top_chatroom': chatroom_name,
            'top_chatroom_count': chatroom_count
        })
    print(f"  最活跃群成员Top 3: {[s['name'] for s in top_senders_overall[:3]]}")

    # 4. 私聊分析
    print("\n分析私聊频次...")
    private_stats = analyze_private_chats(msg_db, sessions, name_map, start_ts, end_ts)
    print(f"  私聊数: {len(private_stats)}")
    print(f"  Top 3私聊:")
    for p in private_stats[:3]:
        print(f"    {p['name']}: {p['message_count']}条消息")

    # 5. 时间分布
    print("\n分析时间分布...")
    time_dist = analyze_time_distribution(msg_db, sessions, start_ts, end_ts)
    print(f"  最活跃小时: {max(time_dist['hourly'], key=lambda x: x['count'])['hour']}点")
    print(f"  最活跃月份: {max(time_dist['monthly'], key=lambda x: x['count'])['month']}")

    # 6. 汇总输出
    result = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'overall': overall,
        'chatrooms': chatroom_stats[:50],
        'private_chats': private_stats[:50],
        'top_senders_in_chatrooms': top_senders_overall,
        'time_distribution': time_dist
    }

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_json}")


if __name__ == '__main__':
    main()
