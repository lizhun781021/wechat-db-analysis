#!/usr/bin/env python3
"""用 all_keys.json 批量解密微信数据库为明文库"""
import json
import os
import sys
from sqlcipher3 import dbapi2 as db

WXDIR = "/Users/lizhun/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/lizhun78_b9a8"
OUTDIR = "/Users/lizhun/Desktop/星小辰工作空间/wechat-db-analysis/decrypted_db_411"
KEYFILE = os.path.join(WXDIR, "all_keys.json")


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
        # 校验
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
    with open(KEYFILE) as f:
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


if __name__ == "__main__":
    main()