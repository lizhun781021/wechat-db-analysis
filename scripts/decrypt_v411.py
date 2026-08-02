#!/usr/bin/env python3
"""
微信4.1.11数据库解密器
======================
发现：4.1.11不再做PBKDF2 256000次迭代派生enc_key，直接用raw key作为enc_key。
只对mac_key做2次PBKDF2迭代。

用法：
    python3 decrypt_v411.py --key <32字节hex密钥> --input <db_storage目录> --output <输出目录>

示例：
    python3 decrypt_v411.py \\
        --key <your_64_char_hex_key> \\
        --input ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<your_account>/db_storage \\
        --output ./decrypted_db

依赖：
    pip install pycryptodome
"""

import hashlib
import hmac
import struct
import os
import sys
import io
import functools
import argparse

print = functools.partial(print, flush=True)

PAGE_SIZE = 4096
SALT_SIZE = 16
IV_SIZE = 16
KEY_SIZE = 32
HMAC_SIZE = 64  # SHA-512
RESERVE = IV_SIZE + HMAC_SIZE  # 80
SQLITE_HEADER = b"SQLite format 3\x00"

from Crypto.Cipher import AES


def derive_mac_key(raw_key, salt):
    """从raw_key派生MAC密钥（2次迭代）"""
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac("sha512", raw_key, mac_salt, 2, dklen=KEY_SIZE)


def decrypt_page(page_buf, enc_key, mac_key, page_num):
    """解密单个页面"""
    offset = 0
    if page_num == 0:
        offset = SALT_SIZE

    # 验证HMAC
    data_end = PAGE_SIZE - RESERVE + IV_SIZE
    mac = hmac.new(mac_key, page_buf[offset:data_end], hashlib.sha512)
    page_no_bytes = struct.pack("<I", page_num + 1)
    mac.update(page_no_bytes)
    calc_mac = mac.digest()

    stored_mac = page_buf[data_end:data_end + HMAC_SIZE]
    if not hmac.compare_digest(calc_mac, stored_mac):
        return None  # HMAC验证失败

    # AES-CBC解密
    iv = page_buf[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + IV_SIZE]
    cipher = AES.new(enc_key, AES.MODE_CBC, iv)

    encrypted = page_buf[offset:PAGE_SIZE - RESERVE]
    decrypted = cipher.decrypt(encrypted)

    # 组装完整页面
    if page_num == 0:
        # 第一页：SQLite头 + 解密数据 + reserve
        return SQLITE_HEADER + decrypted + page_buf[PAGE_SIZE - RESERVE:]
    else:
        return decrypted + page_buf[PAGE_SIZE - RESERVE:]


def decrypt_db(db_path, output_path, raw_key):
    """解密整个数据库文件"""
    file_size = os.path.getsize(db_path)
    total_pages = (file_size + PAGE_SIZE - 1) // PAGE_SIZE

    with open(db_path, "rb") as f:
        first_page = f.read(PAGE_SIZE)

    if first_page[:15] == SQLITE_HEADER[:15]:
        print(f"  已解密，跳过")
        return False

    salt = first_page[:SALT_SIZE]
    enc_key = raw_key  # 4.1.11: 直接用raw key作为enc_key，不做PBKDF2
    mac_key = derive_mac_key(raw_key, salt)

    # 验证第一页
    decrypted_first = decrypt_page(first_page, enc_key, mac_key, 0)
    if decrypted_first is None:
        print(f"  密钥验证失败！")
        return False

    # 解密所有页面
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(db_path, "rb") as fin, open(output_path, "wb") as fout:
        for page_num in range(total_pages):
            page_buf = fin.read(PAGE_SIZE)
            if len(page_buf) < PAGE_SIZE:
                page_buf = page_buf + b'\x00' * (PAGE_SIZE - len(page_buf))

            # 检查是否全零页
            if page_buf == b'\x00' * PAGE_SIZE:
                fout.write(page_buf)
                continue

            decrypted = decrypt_page(page_buf, enc_key, mac_key, page_num)
            if decrypted is None:
                # HMAC验证失败，写入原始数据
                fout.write(page_buf)
            else:
                fout.write(decrypted)

    out_size = os.path.getsize(output_path)
    print(f"  解密成功: {out_size / (1024*1024):.1f}MB ({total_pages}页)")
    return True


def main():
    parser = argparse.ArgumentParser(description="微信4.1.11 WCDB数据库解密器")
    parser.add_argument("--key", required=True, help="32字节Data Key（hex格式，64个字符）")
    parser.add_argument("--input", required=True, help="db_storage输入目录路径")
    parser.add_argument("--output", required=True, help="解密后输出目录路径")
    args = parser.parse_args()

    raw_key = bytes.fromhex(args.key)
    input_dir = os.path.expanduser(args.input)
    output_dir = os.path.expanduser(args.output)

    print(f"密钥: {args.key}")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print()

    # 查找所有.db文件
    db_files = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal"):
                db_files.append(os.path.join(root, f))

    print(f"找到 {len(db_files)} 个数据库文件")
    print()

    success_count = 0
    for db_path in sorted(db_files):
        rel_path = os.path.relpath(db_path, input_dir)
        output_path = os.path.join(output_dir, rel_path)
        print(f"解密: {rel_path}")

        try:
            if decrypt_db(db_path, output_path, raw_key):
                success_count += 1
        except Exception as e:
            print(f"  错误: {e}")

    print(f"\n完成！成功解密 {success_count}/{len(db_files)} 个数据库")
    print("\n注意：微信4.1.11中，message_0.db使用raw key直接作为enc_key（跳过PBKDF2迭代）。")
    print("其他数据库可能使用不同的加密参数，可能无法用同一密钥解密。")


if __name__ == "__main__":
    main()
