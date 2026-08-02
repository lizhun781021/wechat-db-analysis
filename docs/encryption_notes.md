---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'b377de54-d625-4dee-98bb-826ef9e6ae7f'
  PropagateID: 'b377de54-d625-4dee-98bb-826ef9e6ae7f'
  ReservedCode1: 'dbeaef1e-3a81-4a56-8986-3dc6767d59cf'
  ReservedCode2: 'dbeaef1e-3a81-4a56-8986-3dc6767d59cf'
---

# 微信 4.1.11 WCDB 加密技术细节

## 1. WCDB 加密概述

微信 4.x 使用 WCDB（微信定制的 SQLCipher 4 兼容层）对本地 SQLite 数据库进行加密。

- **加密算法**：AES-256-CBC
- **完整性校验**：HMAC-SHA512
- **页面大小**：4096 字节
- **Salt 大小**：16 字节（存储在第一页开头）
- **Reserve 区域**：每页末尾 80 字节（16 字节 IV + 64 字节 HMAC）

## 2. 4.1.11 加密参数变更

### 旧版（4.1.7 及之前）

```
enc_key = PBKDF2-SHA512(raw_key, salt, iterations=256000, dklen=32)
mac_salt = salt XOR 0x3a
mac_key = PBKDF2-SHA512(enc_key, mac_salt, iterations=256000, dklen=32)
```

### 4.1.11（新版本）

```
enc_key = raw_key                                    # 直接使用，不做 PBKDF2！
mac_salt = salt XOR 0x3a
mac_key = PBKDF2-SHA512(enc_key, mac_salt, iterations=2, dklen=32)  # 仅 2 次迭代
```

**关键差异**：
- enc_key 不再经过 PBKDF2 派生，直接使用从内存提取的 raw key
- mac_key 的 PBKDF2 迭代次数从 256000 降到 2

这是一个重要的发现，因为之前所有公开的微信解密工具都假设 enc_key 需要经过 PBKDF2 256000 次迭代派生。使用旧参数验证 4.1.11 的 message_0.db 会全部失败。

> 注意：此变更已确认适用于 `message_0.db`。其他数据库（contact.db、session.db 等）可能使用不同的 per-db 密钥或参数，使用同一 Data Key 验证均失败。推测可能存在 per-db 密钥派生机制。

## 3. 页面结构

```
┌─────────────────────────────────────────────────────────┐
│  Page 0 特有: [Salt 16B]                                 │
│                                                          │
│  加密数据区                                               │
│  (Page 0: 4096 - 16 - 80 = 4000 字节)                    │
│  (其他页: 4096 - 80 = 4016 字节)                         │
│                                                          │
│  ────────────────────────────────────────────────────── │
│  Reserve 区 (80 字节):                                    │
│  [IV 16B] [HMAC-SHA512 64B]                              │
└─────────────────────────────────────────────────────────┘
```

## 4. HMAC 验证算法

```python
# page_num 从 0 开始，HMAC 中使用 page_num + 1
mac = hmac.new(mac_key, page_buf[offset:data_end], hashlib.sha512)
mac.update(struct.pack("<I", page_num + 1))  # 小端序 4 字节页号
calculated_mac = mac.digest()
```

## 5. 解密流程

```python
1. 读取第一页，提取 salt = page_0[:16]
2. enc_key = raw_key  # 4.1.11: 直接使用
3. mac_salt = bytes(b ^ 0x3a for b in salt)
4. mac_key = PBKDF2-SHA512(enc_key, mac_salt, iterations=2, dklen=32)
5. 对每一页:
   a. 提取 stored_hmac = page[-64:]
   b. 计算 calculated_hmac
   c. 如果不匹配 → 跳过（写入原始数据）
   d. 提取 iv = page[-80:-64]
   e. AES-CBC 解密
   f. 第一页特殊处理：在开头写入 "SQLite format 3\x00"
```

## 6. WCDB zstd 压缩

微信 4.x 对部分消息内容使用 zstd 压缩：

- `WCDB_CT_message_content` 字段为 0 → 未压缩，直接使用 `message_content`
- `WCDB_CT_message_content` 字段非 0 → zstd 压缩，需用 zstandard 库解压 `message_content`

约 39.6% 的消息使用压缩。

## 7. 密钥提取方法

### 工具：chatlog (Go 版)

chatlog 通过以下步骤提取密钥：
1. 获取微信进程的内存映射（vmmap）
2. 筛选 MALLOC_SMALL 类型的内存区域
3. 搜索特定 pattern（文件头特征）
4. 在 pattern 附近搜索 32 字节高熵数据块
5. 用验证算法确认正确的 Data Key

### 前置条件

- **SIP 必须禁用**：macOS SIP 阻止进程间内存读取
- **微信需要重签名**：移除 Hardened Runtime，否则无法 attach

```bash
# 禁用 SIP（恢复模式）
csrutil disable

# 重签名微信
codesign --force --sign - --remove-signation /Applications/WeChat.app
```

### 密钥缓存

提取成功后，密钥保存在 `~/.chatlog/chatlog.json`：
```json
{
  "data_key": "bf0b...0146",  // 32 字节 hex
  "img_key": "b33b...37dc"    // 图片解密密钥
}
```

之后无需再次提取，除非微信大版本更新更换了密钥。

## 8. 消息表结构

```
消息表命名：Msg_<md5(username)>

字段：
- local_id: 本地消息ID
- server_id: 服务器消息ID
- local_type: 消息类型（1=文字, 3=图片, 34=语音, 43=视频, 47=表情包, 67=文件, 10000=系统消息）
- sort_seq: 排序序列号
- real_sender_id: 实际发送者ID
- create_time: 创建时间（Unix时间戳）
- status: 消息状态
- message_content: 消息内容（可能被zstd压缩）
- compress_content: 压缩内容
- WCDB_CT_message_content: 压缩标记（0=未压缩, 非0=zstd压缩）
- source: 消息来源
```

### 群聊消息格式

群聊中的文字消息，`message_content` 字段格式为：
```
wxid_xxx:\n实际消息内容
```

可用 `text.split(':\n', 1)` 提取发送者 wxid 和实际内容。

### 联系人映射

contact 表：
- `username`: 微信号/wxid
- `local_type`: 类型（2=群聊, 5=OpenIM账号）
- `nick_name`: 昵称
- `remark`: 备注名
- `delete_flag`: 删除标记

显示名优先级：备注 > 昵称 > username