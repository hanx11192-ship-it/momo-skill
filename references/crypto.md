# 墨墨背单词 MEMO_AES_V3 逆向笔记

> 状态：**签名与加解密算法已逐字节确认；离线解密服务端响应不可行（seed 无法复现）；
> 已改用「读 App 本地 SQLite」路线拿到私有 voc_id，自动化闭环打通。**
> 最后更新：2026-10-10（已 root 的 Android 真机 / frida 17.19.0 验证）

---

## 1. 结论速览

| 项 | 结论 | 置信度 |
|---|---|---|
| 私有 voc_id 获取 | **读 `momo.v425.db` 的 `VOC_TB` 表**（12.9 万词条） | ✅ 真机验证 |
| `e()` 编码 | `T2[T1[base64_std(reverse(s))]]`，**纯 Python 15/15 复现** | ✅ 逐字节 |
| `sha()` | `SHA1hex(x)` | ✅ |
| `da()`/`ea()` | AES-256-CBC + PKCS7；key=`sha256hex(e(seed))[0:32]`，iv=`[32:48]` | ✅ 往返 5/5 |
| 服务端响应离线解密 | **失败**（11/11 样本）；native `da()` 亦返回 NULL | ❌ 已放弃 |

---

## 2. libmomoco.so JNI 方法表（真实地址）

`.data` 段（addr `0x11a88`，off `0x9a88`，size `0x1f0`）在文件里**全为 0**，
必须**先应用 `.rela.dyn`（addr/off `0x658`，size `0x618`）的 `R_AARCH64_RELATIVE`(1027) 重定位**
（取 `r_addend` 写入）才能读出。表项 24 字节 `{name_ptr, sig_ptr, fn_ptr}`，
**中间夹 8 字节指针 + 8 字节计数（非表项）**，不能用固定步长遍历。

| name | 地址 | 签名 |
|---|---|---|
| `s` | **0x426c** | `(String,String,String)String` |
| `p` | 0x4174 | `(ApiEncipher$ParamStatement)String` |
| `p2` | 0x41f0 | `(Map)String` |
| `d` | **0x498c** | `(String)String` |
| `e` | **0x44e4** | `(String)String` |
| `ec` | 0x4498 | `(C)C` |
| `da` | 0x4b38 | `(String,[B)[B` |
| `ea` | 0x4c90 | `(String,[B)[B` |
| `dss` | 0x4c98 | `(String,String,String,String,[B)[B` |
| `sha` | 0x53ac | `(String)String` |
| `init` | 0x7a38 | `(File,MMDBResource...)V` |
| `getVersion` | 0x8234 | `(File)I` |
| `getRevisionInterval` | 0x8598 | `(File,II,String)I` |
| `close` | 0x818c | `()V` |

> ⚠️ 早期笔记把 `0x44e4` 当 `ec`、`0x498c` 当 `e`，**地址全部错位**，已修正。

---

## 3. `e()` @0x44e4 —— 自定义 base64 变体（已完整破解）

### 3.1 反汇编要点

```
0x450c  ldr x8,[x8,#0x520]   ; GetStringLength(s) -> w0 = n
0x4518  scvtf d0,w0 ; bl 0x9780 ; fcvtzs w2,d0
                             ; w2 = (int)(n/2.0) 向上取整（实测 = ceil(n/2) 的等价值）
0x452c  bl #0x4658           ; 0x4658(env, s, w2) -> jarray
0x454c  ldr x8,[x8,#0x110]   ; CallObjectMethod([0x11000+0xce0], arr)
0x4568  ldr x8,[x8,#0x5c0]   ; GetByteArrayElements(obj)
0x4580  ldr x8,[x8,#0x558]   ; GetArrayLength -> w25 = m
0x458c  bl #0x3358           ; 长度 = 4*ceil(m/3)+1（含 NUL）
0x45a8  bl #0x3380           ; ★ 标准 base64 编码（字母表 @0x1554 = A-Za-z0-9+/）
0x45c8  cmp w22,#2 / b.lt    ; 若长度<2 直接返回
0x45d8  adr x9,#0x1e0b       ; T1 表
0x45e0  adr x10,#0x1db0      ; T2 表
0x45e8  loop: buf[i] = T2[ T1[ buf[i] ] ]   ; 循环 m 次（含 '='）
0x4620  ldr x8,[x8,#0x538]   ; NewStringUTF -> 返回
0x463c  mov x0,xzr           ; 长度<2 或参数为 NULL 时返回 NULL
```

### 3.2 `0x4658` 的真实语义

按 **UTF-16 code unit** 读串（`0x46a8 [#0x528]`=`GetStringChars`、`0x4724 ldrh`），
处理 **surrogate pair**（`0x4728 and #0xfc00` / `cmp #0xd800` / `cmp #0xdc00` / `0x4750 cinc`）。
**实测效果 = 把字符串按码点顺序反向拷贝**（hook `0x3380` 输入侧实证）：

```
'AB'     -> b64_in = 'BA'
'abcdef' -> b64_in = 'fedcba'
'ABC'    -> b64_in = 'CBA'
'A'      -> 无输出（长度<2 直接 NULL）
```

### 3.3 T1 / T2 表（从 ELF dump）

- **T1 @0x1e0b**（128 B）：前 43 个 `0x40`，`val['%']=37`、`val['&']=38`、
  `val['0'..'9']=0..9`、`val['=']=39`、`val['A'..'Z']=10..35`、`val['a'..'z']=36..61`
  —— 即**标准 base64 逆表**，无效字符映射到 `0x40`。
- **T2 @0x1db0**（128 B，实际有效 96 B）：
  ```
  9DbHdkrsj13yxX4IB+/oNaEi8YCGzT02FOVZ@tRv   (40 B)
  40 40 40 40 40 40 40 40                     (8 B 填充)
  36 37 4c 65 51 35 6e 66 63 77 68 4a 71 67 50 57 6c 6d 4d 4b 53 70 75 41 55 3d
  ```
  有效取值 0..63 → 前 64 项；其后为填充/续表。

### 3.4 经验实现（纯 Python，已验证 15/15 逐字节一致）

```python
import base64
T1 = ELF[0x1e0b:0x1e0b+128]
T2 = ELF[0x1db0:0x1db0+128]

def e(s: str) -> bytes:
    if len(s) < 2:
        return b""
    b = bytearray(base64.b64encode(s[::-1].encode("latin-1")))
    for i in range(len(b)):
        b[i] = T2[T1[b[i]]]
    return bytes(b)
```

验证样本：

| 输入 | 输出 |
|---|---|
| `AA` | `C04v` |
| `abcdef` | `Zq2hVbof` |
| `A1B2C3` | `E9EUCwIy` |
| `b80d07722afd4abe21c2e2f85d9a51f4d5b0551c` | `V=4DiTyciFC9Zw4DVTJhiTfqEq0UV=4UZFofiBGqVT/Ui=LuZX3dVnvv` |

> 注：`e()` 是**可逆编码**（非加密）。`PR_TB.phrase` / `PR_TB.interpretation`
> 存的就是 `e()` 输出（如 `Zzk=eOoSVz3nVq0neBjne+iSeb4nzB0v`）。

---

## 4. `sha()` @0x53ac 与 `sha256_hex()` @0x51e4

- `sha(x)` = **`SHA1hex(x)`**（`0x531c` → `0x5350 bl 0x6764` 算 20 字节，
  `0x535c-0x5378` 循环 `0x14`=20 次经 `0x5278`=`sprintf("%02x")` 写 hex）
- `sha256_hex(src, dst, len)` = `SHA256(src)` → 64 个 hex 字符写 `dst`

---

## 5. `da()` @0x4b38 / `ea()` @0x4c90 —— AES 解密 / 加密

### 5.1 `da()` 反汇编（权威路径）

```
0x4b7c  mov x21,x0            ; env
0x4b80  bl  #0x44e4           ; ★ e(seed) -> jstring
0x4b94  bl  #0x8b34           ; String.getBytes("UTF-8") -> jbyteArray
0x4bb8  bl  #0x97a0           ; strlen(...) -> x2
0x4bcc  bl  #0x51e4           ; sha256_hex(src, dst=sp+7, len)
0x4bd0  mov w0,#0x21 ; malloc(33) -> key
0x4bdc  mov w0,#0x11 ; malloc(17) -> iv
0x4bfc  bl  #0x97b0           ; __strncpy_chk2(key, digest,    32, 33)
0x4c14  bl  #0x97b0           ; __strncpy_chk2(iv , digest+32, 16, 17)
0x4c18  and w4,w20,#1
0x4c34  bl  #0x4fb8           ; AES crypt(env, ct, key, iv, mode&1)
```

**派生公式（hook 0x4bfc/0x4c14 实测确认）：**

```
d       = sha256hex( e(seed) )
key     = d[0:32]     # 32 个 ASCII 字符 = AES-256 key
iv      = d[32:48]    # 16 个 ASCII 字符 = CBC IV
```

**实测对照**（seed = `b80d07722afd4abe21c2e2f85d9a51f4d5b0551c`）：
```
e(seed)  = "V=4DiTyciFC9Zw4DVTJhiTfqEq0UV=4UZFofiBGqVT/Ui=LuZX3dVnvv"  (56 字符)
sha256hex= 681e69225be13bd94b838aa0929e097bf4e292476a940f095ebb9aa2f85a96f5
key      = b'681e69225be13bd94b838aa0929e097b'
iv       = b'f4e292476a940f09'
```

### 5.2 `0x4fb8` AES crypt

- `0x5038 tbz w22,#0` → bit0=1 走**加密**（`0x503c`，PKCS7 补位）；
  bit0=0 走**解密**（`0x50e8`：`0x5128 bl 0x9620` 标准 CBC，`0x512c-0x5164` PKCS7 校验）。
- `0x3358(len)` = `1 + 4*ceil(len/3)`（含 NUL 的 base64 输出长度）
- `0x3380` = **标准 base64 编码**（字母表 `A-Za-z0-9+/`，尾部 `0x3d`=`'='` 填充）
- `0x8b34` = `String.getBytes("UTF-8")` 的 native 封装
- `0x4c98 dss` = `(String,String,String,String,[B)[B`（多段拼接的变体）

### 5.3 PLT → libc 映射（`.got.plt` @0xd9e8，`.rela.plt` @0xc70）

| 槽 | 符号 | 槽 | 符号 |
|---|---|---|---|
| 0xda18 | free | 0xda48 | memcpy |
| 0xda20 | __stack_chk_fail | **0xda50** | **strlen** |
| 0xda28 | malloc | **0xda58** | **__strncpy_chk2** |
| 0xda30 | qsort | 0xda60 | strncpy |
| 0xda38 | strcmp | 0xda68 | memset |
| 0xda40 | log | 0xda70 | __vsprintf_chk |
| 0xda78 | realloc | 0xda80 | __vsnprintf_chk |

---

## 6. HTTP 层（Java 侧）

### 6.1 请求头 Signature 两段式生成

```java
// c6/000044c6.java:156-159 —— 先塞「原始签名」
String raw = Uri.encode(ApiEncipher.paramsToString(body)
                      + ApiEncipher.paramsToString(query));
req.headers("Signature", raw);

// e2/000065e2.java:186-196 —— interceptor 覆盖
String sig    = req.header("Signature");      // = raw
String rawSig = Uri.decode(sig);
String salt   = ApiEncipher.sha(<某时间串>);   // sha() = SHA1hex
req.headers("Signature",      ApiEncipher.sign(token, salt, rawSig)); // s()
req.headers("Signature-Salt", salt);
req.headers("Algorithm",      "MEMO_AES_V3");
// 调试埋点：
zv9("seed",   salt);                          // ← salt 被命名为 "seed"
zv9("append", "C1f4134a5ac96450dbb7fe64f166a131");
```

- `sign(token, salt, raw)` = `SHA1hex(token + salt + raw + "C1f4134a5ac96450dbb7fe64f166a131")`
- 常量：`TABLE32 = "C1f4134a5ac96450dbb7fe64f166a131"`

### 6.2 响应解密（Java 侧）

```java
// 14/00000914.java  (class c70)
String ce = o39.c(resp, "Content-Encoding");
if (ce == null || !ce.contains("MEMO_AES_V3")) { ... 明文路径 ... }
InputStream in = resp.body.source().inputStream();
k19 req = o39Var.b;                               // o39.b 是 Request（不是 Response）
String seed = req.d.b("Signature");               // ★ seed = 请求头 Signature
byte[] hex  = u71.c(in, new ArrayDeque(20), 0);   // 读全部流（ASCII hex）
byte[] ct   = new byte[hex.length / 2];
for (i) ct[i] = (byte) Integer.parseInt(new String({hex[2i],hex[2i+1]}), 16);
return new InputStreamReader(new GZIPInputStream(
        new ByteArrayInputStream(MMEncipher.decryptAES(seed, ct))), UTF_8);
// MMEncipher.decryptAES(seed, ct) == native da(seed, ct)
```

**body 格式**：`content-encoding: MEMO_AES_V3` 的 body 是 **ASCII hex 文本**
（小写，长度 = 密文字节数 × 2）。解 hex → AES-256-CBC 密文（PKCS7）→ 解密 → gzip → JSON。

---

## 7. ⚠️ 未解问题：服务端响应的 seed

**现象**：用 `Signature` 派生 key/iv 解密 HAR 中 **11 条** MEMO_AES_V3 响应
**全部失败**（PKCS7 不过）；把这些 seed 喂给 **native `da()` 仿真也全部返回 NULL**。

**已排除**：
- 算法错误 —— native `ea`↔`da` 往返 **5/5 PASS**
- key/iv 派生错误 —— hook `0x4bfc`/`0x4c14` 实测与公式**完全一致**
- `e()` 实现错误 —— 纯 Python 与 native **15/15 逐字节一致**
- 密文格式错误 —— 128 / 5024 / 10304 字符皆合法 hex 且为 16 的倍数
- PLT / JNI 槽位映射错误 —— 已全部校正

**已穷举失败的 seed 候选**（各配 sha256/sha1/md5 × k∈{16,32} ×
iv∈{d[32:48],d[16:32],d[:16],zeros} × CBC/ECB）：

```
sig / salt / token / token[:40] / const
e(sig) / e(salt) / e(token) / e(sig+salt) / e(salt+sig) / e(sig+CONST) / e(CONST+sig)
sig+salt / salt+sig / token+salt / salt+token / token+sig / sig+token
sig+CONST / CONST+sig / token+salt+CONST / token+salt+sig
sha1(sig) / sha1(salt) / md5(sig) / md5(salt) / sha256(sig) / sha256(salt)
bytes.fromhex(sig) / bytes.fromhex(salt)
e(sig)+salt / salt+e(sig) / e(sig)+CONST / e(sig)+salt+CONST
token+salt 全排列 / x-user-tag / x-request-id / etag / 请求 body
```

**当前最强假设**：服务端加密响应时用的 seed **并非**最终请求头 `Signature`
（尽管 Java 代码字面如此）。可能原因：
(a) 抓包工具的 header 被改写；
(b) 拦截器写入与最终 header 存在差异；
(c) 服务端另有响应密钥经某头部传递（未识别）。

**影响**：不影响任何**写入**操作（签名链独立成立，服务端已接受）；
仅影响**读取**加密响应。

---

## 8. ✅ 替代路线：读 App 本地数据库（已打通，推荐）

墨墨 App 会把服务端数据**解密后落入本地 SQLite**：

```
/data/data/com.maimemo.android.momo/databases/momo.v425.db   (~94 MB)
    VOC_TB     129,927 行   (id, spelling, ...)  ← id 即私有 voc_id
    PR_TB       45,002 行   (voc_id, phrase, interpretation, ...)  ← 值为 e() 编码
    NT_TB       18,570 行   (voc_id, note, type, ...)
    TAG_VOC_TB  79,711 行
    ...
/data/data/com.maimemo.android.momo/databases/content_file.db (~16 MB)
    content_file 7,685 行   (id, creator_id, object_id, model)
                            model = 明文 JSON（图片/文件元数据）
```

**实测验证**：
```
button -> 57067b78a172044907c607fa   ← 与 HAR 抓包中的私有 voc_id 完全一致 ✅
sleep  -> 57067b69a172044907c60331
the    -> 57e8e7504c91786f32bf7cbf
```

**取库方式**（需 USB 调试 + root）：
```bash
adb shell su -c 'cp /data/data/com.maimemo.android.momo/databases/momo.v425.db /data/local/tmp/x.db && chmod 666 /data/local/tmp/x.db'
adb pull /data/local/tmp/x.db ./momo.v425.db
```

`scripts/voc_db.py` 已封装该流程：`lookup(["button","sleep"])` → `{词: voc_id}`。

---

## 9. frida 环境（真机）

- 设备：已 root 的 Android 真机，已 root（`su` 可用）
- frida-server **17.19.0** ↔ Python frida **17.19.0**
- 目标包：`com.maimemo.android.momo`（主进程名 `Maimemo`）
- **检测**：App 集成腾讯 **metac**（`libmetasec_ml.so` / `libEncryptorP.so`），
  attach 时报 `agent connection closed unexpectedly` / `sync up with agent timed out`。
  规避尝试：patched frida-server（`/data/local/tmp/fsd_patched`）、隐蔽路径
  （`/data/data/tmp2/svc`）、非默认端口（39421 / 51122）、`read()` 层过滤 maps，
  **均未成功**。当前绕过仍待解决。

---

## 10. 依赖

- Python：`capstone` / `unicorn` / `pycryptodome`
  （`unicorn` 常量须 `from unicorn.arm64_const import ...`，顶层无 `UC_ARM64_REG_*`）
- 设备：`adb`（`D:/mcp/adb/platform-tools/adb`）、`frida` 17.19.0
