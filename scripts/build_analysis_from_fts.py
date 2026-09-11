#!/usr/bin/env python3
"""
从解密后的 message_fts.db（全文索引库）构建聊天分析 JSON
==========================================================
用途：当 message_0.db / message_1.db 密钥不可用（数据库轮转换钥）时的兜底数据源。
微信 4.x 的全文索引库 message_fts.db 存有全部已索引消息的：
  原文(acontent) + 会话(session_id) + 发送者(sender_id) + 时间(create_time)，
且其密钥在 2026-09-09 轮转事件中未变更，始终可用。

输出 JSON 结构与 chat_analysis.py 完全一致，可直接喂给 gen_daily_report.py。

口径说明（与 chat_analysis 的差异）：
  - 全文索引只收录带文本的消息（文字/链接/文件名等），图片、语音、表情包等
    未入索引的消息不在统计内，总消息数为"文字类消息"口径。
  - 群聊发送者直接取 sender_id 字段，比 chat_analysis 从内容解析更准确。

用法：
    python3 build_analysis_from_fts.py \
        --fts-db ./decrypted/message_fts.db \
        --contact-db ./decrypted/contact.db \
        --my-wxid lizhun78 \
        --date 2026-09-09 \
        --output analysis_2026-09-09.json

依赖：无（仅标准库）
"""

import sqlite3
import json
import datetime
import argparse
import os
from collections import Counter, defaultdict

# 与 chat_analysis.py 保持一致的消息类型映射
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

FTS_SHARDS = 4  # message_fts_v4_0 ~ message_fts_v4_3


def get_msg_type_name(local_type):
    if local_type in MSG_TYPES:
        return MSG_TYPES[local_type]
    base_type = local_type & 0xFF
    if base_type in MSG_TYPES:
        return MSG_TYPES[base_type]
    return f"其他({local_type})"


def build_name_map(contact_db):
    """username -> 显示名（备注 > 昵称 > username），与 chat_analysis.py 相同"""
    conn = sqlite3.connect(contact_db)
    name_map = {}
    for username, nick, remark in conn.execute(
        "SELECT username, nick_name, remark FROM contact WHERE delete_flag = 0"
    ).fetchall():
        display = remark if remark else (nick if nick else username)
        name_map[username] = display
    conn.close()
    return name_map


def build_id2name(fts_db):
    """name2id 表的 rowid -> username 映射"""
    conn = sqlite3.connect(fts_db)
    id2name = {rid: username for rid, username in conn.execute("SELECT rowid, username FROM name2id").fetchall()}
    conn.close()
    return id2name


def fetch_day_messages(fts_db, start_ts, end_ts):
    """拉取某时间范围内全部索引消息（跨4个分片），按 (会话, 本地消息id) 去重"""
    conn = sqlite3.connect(fts_db)
    msgs = {}  # (session_id, message_local_id) -> {type, sender_id, create_time, parts}
    for i in range(FTS_SHARDS):
        table = f"message_fts_v4_{i}_content"
        # c0=acontent c1=message_local_id c2=sort_seq c3=local_type c4=session_id c5=sender_id c6=create_time
        try:
            rows = conn.execute(
                f"SELECT c0, c1, c2, c3, c4, c5, c6 FROM {table} WHERE c6 BETWEEN ? AND ?",
                (start_ts, end_ts),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for content, lid, seq, lt, sess, sender, ts in rows:
            key = (sess, lid)
            if key not in msgs:
                msgs[key] = {"session_id": sess, "message_local_id": lid,
                             "type": lt, "sender_id": sender, "create_time": ts, "parts": []}
            if seq is not None:
                msgs[key]["parts"].append((seq, content))
    conn.close()
    # 按 sort_seq 排序拼接长消息内容
    for m in msgs.values():
        m["parts"].sort(key=lambda x: x[0])
        m["content"] = "".join(p[1] or "" for p in m["parts"])
    return list(msgs.values())


def main():
    parser = argparse.ArgumentParser(description="从全文索引库构建聊天分析JSON（兜底数据源）")
    parser.add_argument("--fts-db", required=True, help="解密后的 message_fts.db 路径")
    parser.add_argument("--contact-db", required=True, help="解密后的 contact.db 路径")
    parser.add_argument("--my-wxid", required=True, help="自己的 wxid（跨群活跃榜排除自己）")
    parser.add_argument("--date", required=True, help="统计日期 YYYY-MM-DD")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    fts_db = os.path.expanduser(args.fts_db)
    contact_db = os.path.expanduser(args.contact_db)
    report_date = args.date

    dt = datetime.datetime.strptime(report_date, "%Y-%m-%d")
    start_ts = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    end_ts = int(dt.replace(hour=23, minute=59, second=59, microsecond=0).timestamp())

    print(f"=== 微信聊天分析（全文索引库兜底口径） ===")
    print(f"统计日期: {report_date}")

    print("构建映射...")
    name_map = build_name_map(contact_db)
    id2name = build_id2name(fts_db)
    print(f"  联系人: {len(name_map)}, name2id映射: {len(id2name)}")

    print("拉取当天索引消息...")
    messages = fetch_day_messages(fts_db, start_ts, end_ts)
    print(f"  当天消息: {len(messages)}")

    # 消息归属：session username
    for m in messages:
        m["session"] = id2name.get(m["session_id"], f"unknown_session_{m['session_id']}")
        m["sender"] = id2name.get(m["sender_id"], f"unknown_sender_{m['sender_id']}")

    # ---- 总体统计 ----
    all_types = Counter()
    min_time, max_time = 9999999999, 0
    chatroom_msgs = defaultdict(list)   # username -> [msg]
    private_msgs = defaultdict(list)
    for m in messages:
        all_types[get_msg_type_name(m["type"])] += 1
        if m["create_time"] < min_time:
            min_time = m["create_time"]
        if m["create_time"] > max_time:
            max_time = m["create_time"]
        if "@chatroom" in m["session"]:
            chatroom_msgs[m["session"]].append(m)
        elif "@openim" not in m["session"]:
            private_msgs[m["session"]].append(m)

    overall = {
        "total_messages": len(messages),
        "total_chatrooms": len(chatroom_msgs),
        "total_private_chats": len(private_msgs),
        "time_range": [
            datetime.datetime.fromtimestamp(min_time).strftime("%Y-%m-%d %H:%M") if messages else report_date,
            datetime.datetime.fromtimestamp(max_time).strftime("%Y-%m-%d %H:%M") if messages else report_date,
        ],
        "type_breakdown": dict(all_types.most_common()),
    }

    # ---- 群聊统计 ----
    chatroom_stats = []
    sender_counter = Counter()          # 跨群发送者
    sender_chatrooms = defaultdict(Counter)  # 发送者 -> {群名: 数}
    for username, msgs in chatroom_msgs.items():
        type_counts = Counter(get_msg_type_name(m["type"]) for m in msgs)
        room_senders = Counter(m["sender"] for m in msgs)
        display = name_map.get(username, username)
        for s, c in room_senders.items():
            sender_chatrooms[s][display] += c
            sender_counter[s] += c
        chatroom_stats.append({
            "username": username,
            "name": display,
            "message_count": len(msgs),
            "time_range": [report_date, report_date],
            "type_breakdown": dict(type_counts.most_common()),
            "top_senders": [
                {"name": name_map.get(s, s), "username": s, "count": c}
                for s, c in room_senders.most_common(10)
            ],
            "sender_count": len(room_senders),
        })
    chatroom_stats.sort(key=lambda x: x["message_count"], reverse=True)

    # ---- 私聊统计 ----
    private_stats = []
    for username, msgs in private_msgs.items():
        type_counts = Counter(get_msg_type_name(m["type"]) for m in msgs)
        private_stats.append({
            "username": username,
            "name": name_map.get(username, username),
            "message_count": len(msgs),
            "time_range": [report_date, report_date],
            "type_breakdown": dict(type_counts.most_common()),
        })
    private_stats.sort(key=lambda x: x["message_count"], reverse=True)

    # ---- 跨群活跃成员（排除自己）----
    top_senders_overall = []
    for s, c in sender_counter.most_common(30):
        if s == args.my_wxid:
            continue
        top_cr = sender_chatrooms[s].most_common(1)
        top_senders_overall.append({
            "name": name_map.get(s, s),
            "username": s,
            "count": c,
            "top_chatroom": top_cr[0][0] if top_cr else "未知",
            "top_chatroom_count": top_cr[0][1] if top_cr else 0,
        })

    # ---- 时间分布 ----
    hour_dist = [0] * 24
    weekday_dist = [0] * 7
    for m in messages:
        t = datetime.datetime.fromtimestamp(m["create_time"])
        hour_dist[t.hour] += 1
        weekday_dist[t.weekday()] += 1
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    time_distribution = {
        "hourly": [{"hour": h, "count": hour_dist[h]} for h in range(24)],
        "weekly": [{"name": weekday_names[i], "count": weekday_dist[i]} for i in range(7)],
        "monthly": [{"month": report_date[:7], "count": len(messages)}],
        "daily": [{"date": report_date, "count": len(messages)}],
    }

    result = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "message_fts_db",
        "overall": overall,
        "chatrooms": chatroom_stats[:50],
        "private_chats": private_stats[:50],
        "top_senders_in_chatrooms": top_senders_overall,
        "time_distribution": time_distribution,
    }

    with open(os.path.expanduser(args.output), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n总消息: {overall['total_messages']} | 活跃群聊: {len(chatroom_msgs)} | 活跃私聊: {len(private_msgs)}")
    print(f"Top 3 群聊:")
    for c in chatroom_stats[:3]:
        print(f"    {c['name']}: {c['message_count']}条, {c['sender_count']}人发言")
    print(f"Top 3 私聊:")
    for p in private_stats[:3]:
        print(f"    {p['name']}: {p['message_count']}条")
    print(f"\n结果已保存: {args.output}")


if __name__ == "__main__":
    main()
