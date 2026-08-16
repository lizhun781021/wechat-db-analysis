#!/usr/bin/env python3
"""
微信每日聊天报告 - 一键执行脚本
================================
完整链路：解密 → 分析 → 日报HTML → 长图PNG

默认生成"前一天"的微信聊天日报，输出到 daily-reports/YYYY-MM-DD/：
  - 微信聊天日报_YYYY-MM-DD.html   （精简日报网页）
  - 微信聊天日报_YYYY-MM-DD.png    （长图）

用法：
    python3 run_daily_report.py                 # 默认昨天
    python3 run_daily_report.py --date 2026-08-15   # 指定日期
    python3 run_daily_report.py --keep-decrypted   # 保留解密库（默认用完即删）

依赖：
    pip install sqlcipher3 zstandard
    全局 npm: playwright（用于长图生成）
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

# 项目目录（脚本位于 scripts/ 子目录）
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# 我的 wxid（用于排除自己）
MY_WXID = "lizhun78"  # 可改为你的 wxid


def decrypt_db(enc_path, out_path, enc_key):
    """用 sqlcipher 解密单个库到明文"""
    from sqlcipher3 import dbapi2 as db
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    conn = db.connect(enc_path)
    conn.execute(f"PRAGMA key = \"x'{enc_key}'\"")
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
                dest.executemany(
                    f'INSERT INTO "{t}" ({colnames}) VALUES ({placeholders})',
                    [tuple(row) for row in data],
                )
        except Exception:
            pass
    dest.commit()
    dest.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="微信每日聊天报告一键生成")
    parser.add_argument("--date", default=None, help="报告日期 YYYY-MM-DD（默认昨天）")
    parser.add_argument("--keep-decrypted", action="store_true", help="保留解密库不删除")
    args = parser.parse_args()

    # 1. 确定报告日期
    if args.date:
        report_date = args.date
        datetime.datetime.strptime(report_date, '%Y-%m-%d')  # 校验格式
    else:
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        report_date = yesterday.strftime('%Y-%m-%d')

    print(f"=== 微信每日聊天报告 ===")
    print(f"报告日期: {report_date}")

    # 2. 读取密钥
    with open(KEYFILE) as f:
        keys = json.load(f)

    # 3. 解密 message_0.db 和 contact.db
    work_dir = tempfile.mkdtemp(prefix="wx_daily_")
    try:
        msg_out = os.path.join(work_dir, "message_0.db")
        contact_out = os.path.join(work_dir, "contact.db")

        print("\n[1/4] 解密数据库...")
        msg_key = keys.get('message/message_0.db', {}).get('enc_key')
        contact_key = keys.get('contact/contact.db', {}).get('enc_key')
        if not msg_key or not contact_key:
            print("❌ 缺少 message_0.db 或 contact.db 的密钥")
            sys.exit(1)

        msg_src = os.path.join(WXDIR, "db_storage", "message", "message_0.db")
        contact_src = os.path.join(WXDIR, "db_storage", "contact", "contact.db")

        print(f"  解密 message_0.db ...")
        decrypt_db(msg_src, msg_out, msg_key)
        print(f"  解密 contact.db ...")
        decrypt_db(contact_src, contact_out, contact_key)
        print("  解密完成")

        # 4. 运行 chat_analysis.py（限定日期范围）
        print("\n[2/3] 分析聊天数据...")
        analysis_json = os.path.join(work_dir, f"analysis_{report_date}.json")
        chat_cmd = [
            sys.executable, os.path.join(SCRIPTS_DIR, "chat_analysis.py"),
            "--msg-db", msg_out,
            "--contact-db", contact_out,
            "--my-wxid", MY_WXID,
            "--start-date", report_date,
            "--end-date", report_date,
            "--output", analysis_json,
        ]
        subprocess.run(chat_cmd, check=True)

        # 5. 生成日报 HTML
        print("\n[3/3] 生成日报 HTML + 长图...")
        out_dir = os.path.join(PROJECT_DIR, "daily-reports", report_date)
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, f"微信聊天日报_{report_date}.html")

        gen_cmd = [
            sys.executable, os.path.join(SCRIPTS_DIR, "gen_daily_report.py"),
            "--chat-json", analysis_json,
            "--output", html_path,
            "--date", report_date,
        ]
        subprocess.run(gen_cmd, check=True)

        # 6. 生成 PNG 长图
        png_path = os.path.join(out_dir, f"微信聊天日报_{report_date}.png")
        png_cmd = [
            "node", os.path.join(SCRIPTS_DIR, "html2png.js"),
            html_path, png_path, "1280",
        ]
        env = os.environ.copy()
        env["NODE_PATH"] = "/Users/lizhun/.local/share/TeleAgent/runtimes/node/lib/node_modules"
        subprocess.run(png_cmd, check=True, env=env)

        print(f"\n✅ 日报生成完成:")
        print(f"  HTML: {html_path}")
        print(f"  PNG:  {png_path}")

    finally:
        if not args.keep_decrypted:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main()