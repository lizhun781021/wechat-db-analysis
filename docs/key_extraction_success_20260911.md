# 微信数据库轮换密钥提取指南（2026-09-11 实战记录）

## 背景

微信 4.x 会在账期轮换时更换消息库密钥（如 `message_0.db`/`message_1.db`/`message_resource.db`），
旧密钥全部失效。此前依赖"内存 dump 扫描密钥"的方法在新版本下失效——**密钥不再以明文驻留可读内存**，
仅在数据库打开瞬间出现在加密函数参数中。

## 失败路径（均已排除）

| 方法 | 结果 |
|---|---|
| 全量内存 dump（835MB~4938MB）逐字节扫描 | 零命中，密钥不在可读内存 |
| salt 邻近区域高熵候选验证 | 零命中，仅为表结构缓存 |
| key_info.db / key_info.dat 逆向（固定32B段+XOR/窗口） | 非密钥材料 |
| `sqlite3_key` 符号 hook | 不触发：WCDB 静态链接 SQLCipher，不走系统 libsqlite3 导出 |
| 系统 libcrypto EVP 系列 hook | 不触发：静态内嵌 OpenSSL |
| mach_vm_protect 改保护 / mach_vm_remap 重映射 | 保护区域为内核级 guard 页，max_prot=0，无法解 |

## 成功方法：hook CommonCrypto 加密入口

微信 WCDB 加密最终必经系统 `libcommonCrypto.dylib` 的 **`CCCryptorCreateWithMode`**。

### 关键点

- 不能 hook `sqlite3_key`（静态链接，无符号）；要 hook 加密原语
- 参数布局（arm64）：`args[5]` = key 指针，`args[6]` = keyLen
- 仅捕获 `keyLen == 32` 的调用（AES-256 数据库密钥），过滤掉 16 字节的其他用途密钥
- 微信**运行中**打开数据库（如浏览聊天记录）即会触发，无需重启

### frida 脚本核心

```js
var cc = Process.findModuleByName('libcommonCrypto.dylib');
var addr = cc.getExportByName('CCCryptorCreateWithMode');
Interceptor.attach(addr, {
  onEnter: function(args) {
    var keyLen = args[6].toInt32();
    if (keyLen === 32) {
      send({key: hexify(args[5].readByteArray(32))});
    }
  }
});
```

### 验证（v411 HMAC 判据）

```
mac_salt = salt XOR 0x3a
mac_key  = PBKDF2-HMAC-SHA512(raw_key, mac_salt, iterations=2, dklen=32)
mac      = HMAC-SHA512(mac_key, page_body[16:4032] + LE32(page_no+1))
匹配 → 密钥正确
```

**注意**：v411 加密首页解密后不含明文 SQLite 头（解密后需手动拼接 `SQLite format 3\0`），
因此以 **HMAC 匹配**为唯一判据，不要用"解密后是否含 SQLite 头"判断（会误判为失败）。

## 操作流程（轮换后恢复日报）

1. frida attach 运行中的微信，hook `CCCryptorCreateWithMode`
2. 用户打开聊天/发消息触发数据库读写 → 捕获 32B 密钥
3. 对捕获的每个密钥做 v411 HMAC 验证，建立「库 → 密钥」映射
4. 更新 `all_keys.json` 与 `chatlog.json`
5. 重新生成日报（完整消息口径，非 FTS 兜底）

## 遗留场景

- `message_0.db`（历史库）可能在轮换后又单独换钥：微信打开历史聊天时再次 hook 捕获即可
- 轮转前的 factory 快照 `.material` 文件可用旧密钥解密

## 关键文件

- 密钥库：`<wxdir>/all_keys.json`
- 日报脚本：`scripts/run_daily_report.py`（message_1 → message_0 → FTS 三级降级）
- 每日报告：`daily-reports/YYYY-MM-DD/`
