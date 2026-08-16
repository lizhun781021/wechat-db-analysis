#!/usr/bin/env python3
"""用 all_keys.json 批量导出微信数据库为明文库"""
import json
import os
import sys
from sqlcipher3 import dbapi2 as db

# 默认值（可通过命令行参数覆盖；微信目录自动探测）
WXDIR = None
OUTDIR = os.path.join(os.getcwd(), "exported_db_411")
CRED_FILE = None


def detect_wxdir():
    """自动探测微信容器目录：优先包含 all_keys.json 的目录"""
    base = os.path.expanduser("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
    if not os.path.isdir(base):
        return None
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isfile(os.path.join(p, "all_keys.json")):
            return p
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isdir(p) and not name.startswith('.'):
            return p
    return None


def detect_my_wxid(wxdir):
    """从微信容器目录名推导自身 wxid（目录名格式: <wxid>_<hash>）"""
    if not wxdir:
        return None
    return os.path.basename(wxdir).split('_')[0] or None


def export_db(dbname, info):
    src = os.path.join(WXDIR, "db_storage", dbname)
    out = os.path.join(OUTDIR, dbname)
    if not os.path.exists(src):
        return False, "missing"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    try:
        conn = db.connect(src)
        conn.execute(f"PRAGMA key = \"x'{info['enc_key']}'\"")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        conn.row_factory = db.Row

        dest = db.connect(out)
        rows = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY rowid").fetchall()
        for r in rows:
            if not r['sql']:
                continue
            # 跳过 sqlite_sequence 和 FTS 相关对象
            if 'sqlite_sequence' in r['name'] or 'FTS' in r['name'].upper() or 'MMFtsTokenizer' in r['sql']:
                continue
            try:
                dest.execute(r['sql'])
            except Exception as e:
                print(f"    对象 {r['name']} 建表跳过: {str(e)[:60]}")
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
            except Exception as e:
                print(f"    表 {t} 复制跳过: {str(e)[:60]}")
        dest.commit()
        dest.close()
        conn.close()
        return True, f"{len(rows)} objects"
    except Exception as e:
        return False, str(e)[:100]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="用 all_keys.json 批量导出微信数据库")
    parser.add_argument("--outdir", default=None, help="输出目录（默认: exported_db_411）")
    parser.add_argument("--wxdir", default=None, help="微信容器目录（默认自动探测）")
    args = parser.parse_args()

    global WXDIR, OUTDIR, CRED_FILE
    if args.wxdir:
        WXDIR = args.wxdir
        CRED_FILE = os.path.join(WXDIR, "all_keys.json")
    else:
        detected = detect_wxdir()
        if detected:
            WXDIR = detected
            CRED_FILE = os.path.join(WXDIR, "all_keys.json")
            print(f"自动探测微信目录: {WXDIR}")
        else:
            print("❌ 未找到微信容器目录，请用 --wxdir 指定")
            sys.exit(1)
    if args.outdir:
        OUTDIR = os.path.expanduser(args.outdir)

    # 打印探测到的自身 wxid（供上层脚本识别）
    wxid = detect_my_wxid(WXDIR)
    if wxid:
        print(f"检测到账号 wxid: {wxid}")

    if not os.path.isfile(CRED_FILE):
        print(f"❌ 凭据文件不存在: {CRED_FILE}")
        print("   请先确认微信已登录并重启（all_keys.json 在账号目录下）")
        sys.exit(1)

    print(f"凭据文件: {CRED_FILE}")
    print(f"输出目录: {OUTDIR}")
    print()
    with open(CRED_FILE) as f:
        keys = json.load(f)
    ok = fail = 0
    for dbname, info in keys.items():
        s, msg = export_db(dbname, info)
        print(f"[{'OK' if s else 'FAIL'}] {dbname}: {msg}")
        if s:
            ok += 1
        else:
            fail += 1
    print(f"\n成功 {ok}/{len(keys)}, 失败 {fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()