#!/usr/bin/env python3
"""
微信对话摘要引擎
================
用大模型对每个活跃会话生成对话摘要，提取核心事项、决策、待办和商机信号。

流程：
  1. 从解密数据库提取各会话的文字消息
  2. 按时间间隔自动分段（间隔>1小时算一段新对话）
  3. 对每段对话调用大模型生成结构化摘要
  4. 汇总输出 JSON

用法：
    python3 conversation_summary.py \
        --msg-db <msg.db> --contact-db <contact.db> \
        --my-wxid lizhun78 \
        --start-date 2026-09-15 --end-date 2026-09-21 \
        --output summary.json

依赖：pip install zstandard requests
"""

import sqlite3
import hashlib
import json
import datetime
import argparse
import os
import re
import time
import requests
from collections import defaultdict

try:
    import zstandard
    dctx = zstandard.ZstdDecompressor()
except ImportError:
    dctx = None

# 大模型 API 配置
LLM_API_BASE = "http://localhost:8088/v1/chat/completions"
LLM_MODEL = "NewApi/chat-flash"
LLM_TIMEOUT = 60
LLM_MAX_TOKENS = 500

# 会话分段间隔（秒），超过此间隔算一段新对话
SESSION_GAP = 3600  # 1小时

# 每段对话最大消息数（超过则截断，避免token过长）
MAX_MSGS_PER_SESSION = 30

# 每段对话最大字符数
MAX_CHARS_PER_SESSION = 2000


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
    return datetime.datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')


def extract_conversations(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts, top_n=15):
    """提取各会话的文字消息，按活跃度排序，返回 top_n 个会话的对话列表"""
    conn = sqlite3.connect(msg_db)
    cur = conn.cursor()
    conds = ["local_type = 1"]
    params = []
    if start_ts:
        conds.append("create_time >= ?"); params.append(start_ts)
    if end_ts:
        conds.append("create_time <= ?"); params.append(end_ts)
    where = " WHERE " + " AND ".join(conds)

    # 统计每个会话的消息数，排序取 top_n
    chat_counts = []
    for username, info in sessions.items():
        table = info['table']
        try:
            count = cur.execute(f"SELECT COUNT(*) FROM `{table}`{where}", params).fetchone()[0]
            if count >= 3:
                chat_counts.append((username, count))
        except:
            pass
    chat_counts.sort(key=lambda x: x[1], reverse=True)

    conversations = []
    for username, total_count in chat_counts[:top_n]:
        table = sessions[username]['table']
        is_group = '@chatroom' in username
        display_name = name_map.get(username, username)
        try:
            rows = cur.execute(
                f"SELECT message_content, WCDB_CT_message_content, create_time, real_sender_id "
                f"FROM `{table}`{where} ORDER BY create_time ASC", params
            ).fetchall()

            messages = []
            for content, wct, ts, sender_id in rows:
                text = decompress_content(content, wct)
                if not text:
                    continue
                # 群聊去掉发送者前缀
                if is_group and ':\n' in text:
                    parts = text.split(':\n', 1)
                    sender_wxid = parts[0]
                    text_body = parts[1] if len(parts) > 1 else ""
                    sender_name = name_map.get(sender_wxid, sender_wxid)
                else:
                    text_body = text
                    sender_name = "我" if sender_id == my_rowid else display_name
                # 过滤系统消息、表情、纯符号
                text_body = text_body.strip()
                if not text_body or len(text_body) < 1:
                    continue
                if text_body.startswith('<') and text_body.endswith('>'):
                    continue  # XML 系统消息
                messages.append({
                    "sender": sender_name,
                    "text": text_body,
                    "ts": ts,
                    "time": ts_to_str(ts),
                })

            if len(messages) < 3:
                continue

            # 按时间间隔分段
            segments = []
            current_seg = [messages[0]]
            for i in range(1, len(messages)):
                if messages[i]["ts"] - messages[i-1]["ts"] > SESSION_GAP:
                    segments.append(current_seg)
                    current_seg = [messages[i]]
                else:
                    current_seg.append(messages[i])
            if current_seg:
                segments.append(current_seg)

            # 只取消息数>=3的段
            valid_segments = [s for s in segments if len(s) >= 3]

            conversations.append({
                "username": username,
                "display_name": display_name,
                "is_group": is_group,
                "total_messages": len(messages),
                "segments": valid_segments,
            })
        except:
            pass

    conn.close()
    return conversations


def format_dialogue(messages):
    """将消息列表格式化为对话文本"""
    lines = []
    total_chars = 0
    for msg in messages[:MAX_MSGS_PER_SESSION]:
        line = f'{msg["sender"]}({msg["time"]}): {msg["text"]}'
        if total_chars + len(line) > MAX_CHARS_PER_SESSION:
            break
        lines.append(line)
        total_chars += len(line)
    return "\n".join(lines)


def call_llm(dialogue_text, chat_name, is_group):
    """调用大模型生成对话摘要"""
    chat_type = "群聊" if is_group else "私聊"
    prompt = f"""请分析以下微信{chat_type}对话记录，用简洁的中文输出结构化摘要。

要求：
1. 核心事项：这段对话主要讨论了什么（1-2句话）
2. 关键决策：有没有达成什么决定或共识（没有则写"无"）
3. 待办承诺：谁答应做什么、有什么deadline（没有则写"无"）
4. 商机信号：有没有涉及需求、采购、合作、流失等商业信号（没有则写"无"）

格式（严格遵守）：
核心事项：xxx
关键决策：xxx
待办承诺：xxx
商机信号：xxx

对话记录（{chat_name}）：
{dialogue_text}"""

    try:
        resp = requests.post(
            LLM_API_BASE,
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": 0.3,
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[摘要失败: {e}]"


def parse_summary(text):
    """将大模型返回的文本解析为结构化摘要"""
    result = {"核心事项": "", "关键决策": "", "待办承诺": "", "商机信号": ""}
    for key in result:
        pattern = f"{key}[：:]\\s*(.+?)(?:\\n|$)"
        m = re.search(pattern, text)
        if m:
            result[key] = m.group(1).strip()
    return result


def summarize_conversations(msg_db, contact_db, my_wxid, start_ts, end_ts, top_n=15):
    """主流程：提取对话 → 调大模型 → 返回摘要"""
    print("构建联系人映射...")
    name_map = build_name_map(contact_db)
    print(f"  联系人: {len(name_map)}")

    print("构建会话映射...")
    sessions, id2name = build_session_map(msg_db)
    my_rowid = None
    for rid, uname in id2name.items():
        if uname == my_wxid:
            my_rowid = rid
            break
    print(f"  会话: {len(sessions)}, 我的rowid: {my_rowid}")

    print("提取对话内容...")
    conversations = extract_conversations(msg_db, sessions, name_map, id2name, my_rowid, start_ts, end_ts, top_n)
    print(f"  提取了 {len(conversations)} 个会话")

    summaries = []
    total_segments = sum(len(c["segments"]) for c in conversations)
    print(f"  共 {total_segments} 段对话需要摘要")

    done = 0
    for conv in conversations:
        chat_name = conv["display_name"]
        is_group = conv["is_group"]
        seg_summaries = []

        # 每个会话最多摘要3段（按消息数最多的段优先）
        top_segments = sorted(conv["segments"], key=lambda s: len(s), reverse=True)[:2]
        top_segments.sort(key=lambda s: s[0]["ts"])  # 恢复时间顺序

        for seg in top_segments:
            dialogue = format_dialogue(seg)
            if not dialogue:
                continue
            done += 1
            print(f"  [{done}/{total_segments}] {chat_name} ({len(seg)}条消息)...", end="", flush=True)
            raw = call_llm(dialogue, chat_name, is_group)
            parsed = parse_summary(raw)
            seg_summaries.append({
                "time_range": f"{seg[0]['time']} ~ {seg[-1]['time']}",
                "message_count": len(seg),
                "summary": parsed,
                "raw": raw,
            })
            print(" OK")

        if seg_summaries:
            summaries.append({
                "chat_name": chat_name,
                "is_group": is_group,
                "total_messages": conv["total_messages"],
                "segment_count": len(conv["segments"]),
                "summaries": seg_summaries,
            })

    return {"summaries": summaries, "model": LLM_MODEL, "total_chats": len(summaries)}


def main():
    parser = argparse.ArgumentParser(description="微信对话摘要引擎")
    parser.add_argument("--msg-db", required=True, help="解密后的消息数据库路径")
    parser.add_argument("--contact-db", required=True, help="解密后的联系人数据库路径")
    parser.add_argument("--my-wxid", required=True, help="自己的 wxid")
    parser.add_argument("--start-date", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--top-n", type=int, default=15, help="摘要的会话数量（默认15）")
    args = parser.parse_args()

    start_ts, end_ts = parse_date_range(args.start_date, args.end_date)
    print(f"=== 微信对话摘要 ===")
    print(f"统计范围: {args.start_date or '最早'} ~ {args.end_date or '最近'}")
    print(f"模型: {LLM_MODEL}")

    result = summarize_conversations(
        os.path.expanduser(args.msg_db),
        os.path.expanduser(args.contact_db),
        args.my_wxid,
        start_ts, end_ts,
        args.top_n,
    )

    # 合并到输出
    output = {
        "generated_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "date_range": [args.start_date or "", args.end_date or ""],
        "model": LLM_MODEL,
        "total_chats": result["total_chats"],
        "conversation_summaries": result["summaries"],
    }

    out_path = os.path.expanduser(args.output)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n对话摘要完成，结果已保存: {out_path}")


if __name__ == '__main__':
    main()
