#!/usr/bin/env python3
"""
微信聊天深度分析 - 一键执行脚本
================================
完整链路：解密 → 深度分析（12项） → 综合报告HTML → 长图PNG

支持模式：
  --mode daily    昨天单日（默认）
  --mode weekly   最近7天
  --mode monthly  最近30天
  --mode annual   今年1月1日至今
  --mode custom   自定义日期范围（需配合 --start / --end）

输出到 insights-reports/YYYY-MM-DD/：
  - 微信深度分析_YYYY-MM-DD.html
  - 微信深度分析_YYYY-MM-DD.png
  - deep_analysis_YYYY-MM-DD.json

用法：
    python3 run_insights_report.py                      # 默认昨天
    python3 run_insights_report.py --mode weekly          # 最近7天
    python3 run_insights_report.py --mode custom --start 2026-09-01 --end 2026-09-21

依赖：pip install sqlcipher3 zstandard pycryptodome
     全局 npm: playwright
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import datetime

# 微信数据目录
WXDIR = "/Users/lizhun/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/lizhun78_b9a8"
KEYFILE = os.path.join(WXDIR, "all_keys.json")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MY_WXID = "lizhun78"


def decrypt_db(enc_path, out_path, enc_key):
    """用 sqlcipher 解密单个库到明文"""
    from sqlcipher3 import dbapi2 as db
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    conn = db.connect(enc_path)
    conn.execute(f'PRAGMA key = "x\'{enc_key}\'"')
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    conn.row_factory = db.Row

    dest = db.connect(out_path)
    rows = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY rowid").fetchall()
    for r in rows:
        if not r['sql']:
            continue
        if 'sqlite_sequence' in r['name'] or 'FTS' in r['name'].upper() or 'MMFtsTokenizer' in r['sql']:
            continue
        try:
            dest.execute(r['sql'])
        except Exception:
            pass
    tables = [r['name'] for r in rows if r['type'] == 'table']
    for t in tables:
        if 'sqlite_sequence' in t or 'FTS' in t.upper():
            continue
        try:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
            if not cols:
                continue
            colnames = ",".join(f'"{c}"' for c in cols)
            placeholders = ",".join("?" * len(cols))
            data = conn.execute(f'SELECT {colnames} FROM "{t}"').fetchall()
            if data:
                dest.executemany(f'INSERT INTO "{t}" ({colnames}) VALUES ({placeholders})',
                                 [tuple(row) for row in data])
        except Exception:
            pass
    dest.commit()
    dest.close()
    conn.close()


def get_date_range(mode, start=None, end=None):
    """根据模式返回 (start_date, end_date)"""
    today = datetime.date.today()
    if mode == 'daily':
        d = today - datetime.timedelta(days=1)
        return d.strftime('%Y-%m-%d'), d.strftime('%Y-%m-%d')
    elif mode == 'weekly':
        return (today - datetime.timedelta(days=7)).strftime('%Y-%m-%d'), (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    elif mode == 'monthly':
        return (today - datetime.timedelta(days=30)).strftime('%Y-%m-%d'), (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    elif mode == 'annual':
        return f"{today.year}-01-01", (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    elif mode == 'custom':
        if not start or not end:
            print("❌ custom 模式需要 --start 和 --end 参数")
            sys.exit(1)
        return start, end
    else:
        print(f"❌ 未知模式: {mode}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="微信聊天深度分析一键生成")
    parser.add_argument("--mode", default="daily",
                        choices=["daily", "weekly", "monthly", "annual", "custom"],
                        help="分析模式")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD（custom模式必填）")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（custom模式必填）")
    parser.add_argument("--keep-decrypted", action="store_true", help="保留解密库不删除")
    args = parser.parse_args()

    start_date, end_date = get_date_range(args.mode, args.start, args.end)
    report_label = end_date  # 用结束日期作为报告标识

    print(f"=== 微信聊天深度分析 ===")
    print(f"分析模式: {args.mode}")
    print(f"统计范围: {start_date} ~ {end_date}")

    # 读取密钥
    with open(KEYFILE) as f:
        keys = json.load(f)

    work_dir = tempfile.mkdtemp(prefix="wx_deep_")
    try:
        msg_out = os.path.join(work_dir, "message_0.db")
        contact_out = os.path.join(work_dir, "contact.db")

        print("\n[1/5] 解密数据库...")
        msg_key = keys.get('message/message_1.db', {}).get('enc_key') or \
                  keys.get('message/message_0.db', {}).get('enc_key')
        contact_key = keys.get('contact/contact.db', {}).get('enc_key')
        if not contact_key:
            print("❌ 缺少 contact.db 密钥")
            sys.exit(1)
        if not msg_key:
            print("❌ 缺少消息数据库密钥")
            sys.exit(1)

        # 优先 message_1.db（当前消息库），次选 message_0.db
        msg1_src = os.path.join(WXDIR, "db_storage", "message", "message_1.db")
        msg0_src = os.path.join(WXDIR, "db_storage", "message", "message_0.db")
        msg1_key = keys.get('message/message_1.db', {}).get('enc_key')

        decrypted = False
        if msg1_key and os.path.exists(msg1_src):
            print("  解密 message_1.db...")
            try:
                decrypt_db(msg1_src, msg_out, msg1_key)
                decrypted = True
            except Exception as e:
                print(f"  ⚠️ message_1.db 解密失败: {e}")
        if not decrypted and os.path.exists(msg0_src):
            print("  解密 message_0.db...")
            try:
                decrypt_db(msg0_src, msg_out, keys.get('message/message_0.db', {}).get('enc_key'))
                decrypted = True
            except Exception as e:
                print(f"  ⚠️ message_0.db 解密失败: {e}")
        if not decrypted:
            print("❌ 消息数据库解密失败")
            sys.exit(1)

        print("  解密 contact.db...")
        contact_src = os.path.join(WXDIR, "db_storage", "contact", "contact.db")
        decrypt_db(contact_src, contact_out, contact_key)
        print("  解密完成")

        # 运行深度分析
        print("\n[2/5] 深度分析（30项）...")
        analysis_json = os.path.join(work_dir, f"deep_{report_label}.json")
        analysis_cmd = [
            sys.executable, os.path.join(SCRIPTS_DIR, "deep_analysis.py"),
            "--msg-db", msg_out,
            "--contact-db", contact_out,
            "--my-wxid", MY_WXID,
            "--start-date", start_date,
            "--end-date", end_date,
            "--output", analysis_json,
        ]
        subprocess.run(analysis_cmd, check=True)

        # 对话摘要（大模型）
        print("\n[2.5/5] 对话摘要（大模型）...")
        summary_json = os.path.join(work_dir, f"summary_{report_label}.json")
        summary_cmd = [
            sys.executable, os.path.join(SCRIPTS_DIR, "conversation_summary.py"),
            "--msg-db", msg_out,
            "--contact-db", contact_out,
            "--my-wxid", MY_WXID,
            "--start-date", start_date,
            "--end-date", end_date,
            "--output", summary_json,
        ]
        try:
            subprocess.run(summary_cmd, check=True)
            # 合并摘要到分析JSON
            with open(analysis_json, 'r', encoding='utf-8') as f:
                analysis_data = json.load(f)
            with open(summary_json, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
            analysis_data["conversation_summaries"] = summary_data.get("conversation_summaries", [])
            with open(analysis_json, 'w', encoding='utf-8') as f:
                json.dump(analysis_data, f, ensure_ascii=False, indent=2)
            print("  对话摘要已合并到分析结果")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠️ 对话摘要失败（跳过）: {e}")

        # 生成报告 HTML
        print("\n[3/5] 生成综合报告 HTML...")
        out_dir = os.path.join(PROJECT_DIR, "insights-reports", report_label)
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, f"微信深度分析_{report_label}.html")
        gen_cmd = [
            sys.executable, os.path.join(SCRIPTS_DIR, "gen_insights_report.py"),
            "--analysis-json", analysis_json,
            "--output", html_path,
        ]
        subprocess.run(gen_cmd, check=True)

        # 复制 JSON 到输出目录
        import shutil as sh
        json_out = os.path.join(out_dir, f"deep_analysis_{report_label}.json")
        sh.copy2(analysis_json, json_out)

        # 生成 PNG 长图
        print("\n[4/5] 生成 PNG 长图...")
        png_path = os.path.join(out_dir, f"微信深度分析_{report_label}.png")
        png_cmd = [
            "node", os.path.join(SCRIPTS_DIR, "html2png.js"),
            html_path, png_path, "1280",
        ]
        env = os.environ.copy()
        env["NODE_PATH"] = "/Users/lizhun/.local/share/TeleAgent/runtimes/node/lib/node_modules"
        subprocess.run(png_cmd, check=True, env=env)

        print(f"\n✅ 深度分析完成:")
        print(f"  HTML: {html_path}")
        print(f"  PNG:  {png_path}")
        print(f"  JSON: {json_out}")

    finally:
        if not args.keep_decrypted:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
