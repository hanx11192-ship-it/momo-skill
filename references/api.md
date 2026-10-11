# 墨墨背单词 API 参考（Skill 用）

> 本文档记录「AI 解释单词 → 写入墨墨 App（释义 / 例句 / 助记）」所需接口。
> 所有内容均经实测验证（2026-10-10 实测验证）。
> 权威 schema 来源：墨墨开放 API v1 官方 schema（墨墨开放 API v1 定义）

---

## 目录

- [1. 总体架构](#1-总体架构)
- [2. 认证与凭证](#2-认证与凭证)
- [3. 公共约定](#3-公共约定)
- [4. 词条查询](#4-词条查询)
- [5. 释义 API](#5-释义-api)
- [6. 例句 API](#6-例句-api)
- [7. 助记 API（含图片）](#7-助记-api含图片)
- [8. 图片上传（App 私有）](#8-图片上传app-私有)
- [9. 完整调用示例](#9-完整调用示例)
- [10. 注意事项与踩坑](#10-注意事项与踩坑)

---

## 1. 总体架构

Skill 涉及**两个域**、**两套凭证**：

| 域 | Base URL | 用途 | 凭证 |
|---|---|---|---|
| **开放 API** | `https://open.maimemo.com/open/api/v1/memo` | 释义 / 例句 / 助记（文本） / 词条查询 / 词本 | `open_token`（Bearer，24h） |
| **App 私有** | `https://backup.maimemostatus.com` | 图片上传 + **图片助记（图例）创建** | `web_token`（header，约 1 年） |

**关键规则：**
- 释义 / 例句 是**独立资源**，各有自己的 id，**不是**助记。
- 文本助记（`note_type` = `其他` / `谐音`）走开放 API。
- **图片助记（`note_type` = `图例`）必须走 App 私有域** —— 走开放 API 会返回 201 但**图片挂不上**。

---

## 2. 认证与凭证

### 2.1 open_token（开放 API）

- 获取：`python scripts/open_token.py`（OAuth2 授权码流程复刻）
- 存储：`scripts/cfg/token.json` → 顶层键 `open_token.open_token`
- 有效期：**24 小时**（`expire_ts` 字段可用于过期判断）
- 用法：

```http
Authorization: Bearer <open_token>
```

### 2.2 web_token（App 私有域）

- 获取：`python scripts/web_token.py`（登录 `www.maimemo.com/auth/login`）
- 存储：`scripts/cfg/token.json` → 顶层键 `web_token.web_token`
- 有效期：**约 1 年**（cookie Max-Age = 31104000）
- 用法（注意不是 Bearer）：

```http
token: <web_token>
x-user-tag: <user_tag 首次运行自动生成>
User-Agent: Maimemo/5.6.05_904 okhttp/4.9.2 Android/15 Channel/Vivo CustomOS/ColorOS (15.0.0.840) Device/Android+Phone (arm64)
```

### 2.3 账号配置

`scripts/cfg/cof.json`：

```json
{"account": "your_account@example.com", "password": "********"}
```

两个脚本共用此文件，凭证体系**全自动**。

### 2.4 Token 域限制（重要）

| 凭证 | 开放 API | App 私有域 |
|---|---|---|
| `open_token` | ✅ 可用 | ❌ 不可用 |
| `web_token` | ❌ 401 | ✅ 可用 |

---

## 3. 公共约定

### 3.1 响应格式

**成功：**

```json
{"errors": [], "data": { ... }, "success": true}
```

**失败：**

```json
{"errors": [{"code": "xxx_yyy", "msg": "人类可读信息", "info": ""}], "success": false}
```

### 3.2 HTTP 状态码

| 码 | 含义 |
|---|---|
| 200 | 查询成功 / 更新成功 / 删除成功 |
| **201** | **创建成功**（注意与 200 区分） |
| 400 | 参数错误（`common_invalid_param`）或业务限制 |
| 401 | 认证失败（`user_unauthorized` / `signature_missing_signature`） |
| 403 | 权限不足 |
| 404 | 资源不存在（`common_not_found` / `note_not_found`） |

### 3.3 频控

- 10 秒 20 次
- 60 秒 40 次
- 5 小时 2000 次（墨墨背单词）
- **每天最多创建 600 条内容**（例句 + 助记 + 释义合计）

### 3.4 状态枚举

| 资源 | 可选值 |
|---|---|
| 释义 `status` | `PUBLISHED` / `UNPUBLISHED` / `DELETED` |
| 例句 `status` | `PUBLISHED` / `DELETED` |
| 助记 `status` | `PUBLISHED` / `DELETED` |

> `PUBLISHED` = 公开（他人可见）；`UNPUBLISHED` = 仅自己可见。

### 3.5 tags 白名单（实测）

标签按**资源类型**分开，互不通用：

**考纲类（释义 / 例句 通用）**

| 结果 | 取值 |
|---|---|
| ✅ 合法 | `考研`、`四级`、`六级`、`雅思`、`托福`、`GRE`、`专四`、`专八` |
| ❌ 无效 | `高考`、`柯林斯`、`牛津`、`API测试`、`我的收藏` |

**学段类（例句适用）**

| 结果 | 取值 |
|---|---|
| ✅ 合法 | `小学`、`初中`、`高中` |
| ❌ 无效 | — |

**释义风格类**

| 结果 | 取值 |
|---|---|
| ✅ 合法 | `简明`、`详细` |
| ❌ 无效 | `精编`、`柯林斯` |

> - 无效标签返回 `interpretation_invalid_tag`（释义）/ `phrase_invalid_tag`（例句）。
> - 例句接口会**自动追加** `ext:mod:quality` 等系统标签，回读时能看到。
> - **可用标签集合可能还有未枚举项**，遇到无效标签换一个即可，不必强试。

---

## 4. 词条查询

### 4.1 按拼写查词拿 voc_id

```http
GET https://open.maimemo.com/open/api/v1/memo/vocabulary?spelling=button
Authorization: Bearer <open_token>
```

**响应：**

```json
{
  "errors": [],
  "data": {
    "voc": {
      "id": "voc-JVJBtoVTKs3Bt5B7AGMiur32FgTZGbJgJtADJwLZvL85xVR3314b5LecLJx6R0SI",
      "spelling": "button"
    }
  },
  "success": true
}
```

> `voc.id` 后续所有接口都用它。

### 4.2 其他查询接口

| 接口 | 说明 |
|---|---|
| `GET /memo/vocabulary/query` | 批量查询单词 |
| `GET /memo/vocabulary` | 词库遍历 |

---

## 5. 释义 API

> 释义 = 单词的中文解释（如 `n. 按钮；纽扣`），是**独立资源**。

### 5.1 获取释义

```http
GET https://open.maimemo.com/open/api/v1/memo/interpretations?voc_id=<voc_id>
Authorization: Bearer <open_token>
```

**响应：**

```json
{
  "errors": [],
  "data": {
    "interpretations": [{
      "id": "intp-B-bHkZX3XbChusADbNWbyeaOclhn8WI01alrf617TAs-kjMID0w-G79GUPyZDei8",
      "interpretation": "n. 按钮；纽扣\nv. 扣上；扣紧",
      "tags": ["考研"],
      "status": "PUBLISHED",
      "created_time": "2026-10-10T01:01:29.016Z",
      "updated_time": "2026-10-10T04:52:56.775Z"
    }]
  },
  "success": true
}
```

> 只返回**自己创建**的释义，不含官方词库内容。

### 5.2 创建释义

```http
POST https://open.maimemo.com/open/api/v1/memo/interpretations
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "interpretation": {
    "voc_id": "<voc_id>",
    "interpretation": "n. 按钮；纽扣\nv. 扣上；扣紧",
    "tags": ["考研"],
    "status": "PUBLISHED"
  }
}
```

**响应：`201`**

```json
{"errors": [], "data": {"interpretation": {"id": "intp-...", "interpretation": "...", "tags": ["考研"], "status": "PUBLISHED"}}, "success": true}
```

**必填字段：** `voc_id`、`interpretation`、`tags`、`status`

> **`tags` 可选值：** 考纲类（`考研`/`四级`/`六级`/`雅思`/`托福`/`GRE`/`专四`/`专八`）+ 风格类（`简明`/`详细`）→ 详见 [3.5 tags 白名单](#35-tags-白名单实测)。
> 例：`"tags": ["简明"]` 表示"简明"风格的释义，App 中"类型"一栏会显示。

### 5.3 更新释义

```http
POST https://open.maimemo.com/open/api/v1/memo/interpretations/{id}
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "id": "<interpretation_id>",
  "interpretation": {
    "interpretation": "n. 按钮（更新后）",
    "tags": ["考研"],
    "status": "PUBLISHED"
  }
}
```

> 注意 `id` 在**顶层**，`interpretation` 对象里不需要 `voc_id`。

### 5.4 删除释义

```http
DELETE https://open.maimemo.com/open/api/v1/memo/interpretations/{id}
Authorization: Bearer <open_token>
```

**响应：`200`** → `{"errors": [], "success": true}`

> 删除用标准 HTTP `DELETE`，无 body。

---

## 6. 例句 API

> 例句 = 英文句子 + 中文翻译，是**独立资源**。

### 6.1 获取例句

```http
GET https://open.maimemo.com/open/api/v1/memo/phrases?voc_id=<voc_id>
Authorization: Bearer <open_token>
```

**响应：**

```json
{
  "errors": [],
  "data": {
    "phrases": [{
      "id": "ph-tg5mS77cqLzNjie0Rd2S7-y7W709PNnvUuqwet-hsxAn8w0Y0qQAezTs49XELKkM",
      "phrase": "Click the button to confirm your choice.",
      "interpretation": "点击按钮确认你的选择。",
      "origin": "大肥鱼创建",
      "tags": ["小学", "ext:mod:quality"],
      "status": "PUBLISHED",
      "created_time": "2026-10-10T05:24:52.545Z",
      "updated_time": "2026-10-10T05:24:52.545Z"
    }]
  },
  "success": true
}
```

### 6.2 创建例句

```http
POST https://open.maimemo.com/open/api/v1/memo/phrases
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "phrase": {
    "voc_id": "<voc_id>",
    "phrase": "Click the button to confirm your choice.",
    "interpretation": "点击按钮确认你的选择。",
    "tags": ["小学"],
    "origin": "大肥鱼创建"
  }
}
```

**响应：`201`** → 回读时 `tags` 会被追加系统标签（如 `ext:mod:quality`）

**必填字段：** `voc_id`、`phrase`、`interpretation`、`tags`、`origin`

> **`origin` = 来源标签**（App 中"来源"那一栏显示的内容）。
> 可自由填写文本（实测 `大肥鱼创建` 原样保存并正确显示），也常填 `考研` 等；可为空字符串 `""`。

> ⚠️ **`phrase_single_voc` 限制**：例句必须**至少包含 2 个单词**。
> 若 `phrase` 只有一个单词（如 `"__T__"`、`"apple"`），返回 400 `phrase_single_voc`（"例句不能只包含一个单词。"）。

### 6.3 更新例句

```http
POST https://open.maimemo.com/open/api/v1/memo/phrases/{id}
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "id": "<phrase_id>",
  "phrase": {
    "phrase": "Push the button to start the machine.",
    "interpretation": "按下按钮启动机器。",
    "tags": ["考研"],
    "origin": ""
  }
}
```

**必填字段：** `phrase`（对象）、`id`（顶层）

### 6.4 删除例句

```http
DELETE https://open.maimemo.com/open/api/v1/memo/phrases/{id}
Authorization: Bearer <open_token>
```

**响应：`200`** → `{"errors": [], "success": true}`

---

## 7. 助记 API（含图片）

> 助记 = 用户自创的记忆方法。文本助记走开放 API，**图片助记走私有域**。

### 7.1 获取助记

```http
GET https://open.maimemo.com/open/api/v1/memo/notes?voc_id=<voc_id>
Authorization: Bearer <open_token>
```

**响应：**

```json
{
  "errors": [],
  "data": {
    "notes": [{
      "id": "nt-ofUpuSyq4NyPTQYhzbRpr5E_DSDgD8XmoV3PBXYEFgBJySjnAxKMzxMojQ5mobnY",
      "note": "",
      "note_type": "图例",
      "status": "UNPUBLISHED",
      "created_time": "2026-10-10T05:10:02.478Z",
      "updated_time": "2026-10-10T05:10:02.478Z"
    }]
  },
  "success": true
}
```

> ⚠️ 开放 API 返回的 notes **不包含 `files` 字段**，图片信息只在 App 私有侧可见。

### 7.2 创建文本助记（开放 API）

```http
POST https://open.maimemo.com/open/api/v1/memo/notes
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "note": {
    "voc_id": "<voc_id>",
    "note_type": "其他",
    "note": "联想：按钮就是按下去的那个小块。",
    "publish": false
  }
}
```

**响应：`201`**

**必填字段：** `voc_id`、`note_type`、`note`

**可用 `note_type`：** `其他`、`谐音`（`私有` / `笔记` / `图片` 会 503）

**数量限制（实测）：**

| 类型 | 同词上限 | 超限错误 |
|---|---|---|
| `图例`（图片） | **1 条** | `400 note_create_limitation` |
| `其他` / `谐音`（文本） | **2 条**（实测第 3 条被拒） | `400 note_create_limitation` |

> - **图例与文本可共存**：同一单词可同时有 1 条图例 + 多条文本助记。
> - 实测在已有 1 条图例的情况下，成功创建了 **2 条**文本助记（`其他` + `谐音`），**第 3 条**返回 `note_create_limitation`。
> - 若需要更多内容，建议改用**释义 / 例句**接口（它们是独立资源，不受此限制）。

### 7.3 更新助记

```http
POST https://open.maimemo.com/open/api/v1/memo/notes/{id}
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "note": {
    "note": "更新后的内容",
    "note_type": "其他",
    "status": "PUBLISHED"
  }
}
```

> `note` 必须嵌套成**对象**。`note_type` 需与原值一致。**`voc_id` 不用传。**

### 7.4 删除助记（软删除）

```http
POST https://open.maimemo.com/open/api/v1/memo/notes/{id}
Authorization: Bearer <open_token>
Content-Type: application/json

{
  "note": {
    "note": "<原内容>",
    "note_type": "图例",
    "status": "DELETED"
  }
}
```

**响应：`201`**（status 变为 `DELETED`）

> ⚠️ 助记删除**不能用 HTTP `DELETE`**（→ 400 / 404）。
> ⚠️ 必须用 `POST` + `status: "DELETED"`。
> ⚠️ 图例助记的 `note` 传空字符串 `""` 即可。

---

## 8. 图片上传（App 私有）

> **先上传拿 file_id，再用它建图例助记。**

### 8.1 上传图片

```http
POST https://backup.maimemostatus.com/api/v1/content/files
Content-Type: multipart/form-data; boundary=<boundary>
token: <web_token>
x-user-tag: <user_tag 首次运行自动生成>
User-Agent: Maimemo/5.6.05_904 okhttp/4.9.2 Android/15 ...
```

**multipart 8 个字段（缺一不可）：**

| 字段 | 值 |
|---|---|
| `file` | 图片二进制（附 `filename` + `Content-Type`） |
| `file_name` | 文件名，如 `测试_button.png` |
| `object_class` | `NOTE` |
| `publish` | `false` |
| `app_version` | `5.6.05_904` |
| `android_version` | `15` |
| `device` | `Phone`（任意设备型号均可） |
| `android_channel` | `vivo` |

> ✅ **此接口不需要 `Signature`**（实测无签名 → 200）。
> 裸奔（不带 `token`）→ 401 `user_unauthorized`。

**响应：`200`**

```json
{
  "errors": [],
  "data": {
    "file": {
      "id": "6ac9c8aa163ba7766db8ccab",
      "file_hash": "c7b74eec89eede3575ea8aa3231ca8cc",
      "creator_id": <用户ID>,
      "creator_type": "USER",
      "object_class": "NOTE",
      "size": 87891,
      "storage_provider": "COS",
      "formats": [{
        "path": "NOTE/5cc6a3bb-...-.png",
        "size": 87891,
        "format": "COMPRESSED",
        "url": "https://content-files-1317916700.cos.ap-guangzhou.myqcloud.com/NOTE/....png?q-signature=...",
        "width": 318,
        "height": 180,
        "url_expired_time": "2026-10-17T05:07:52.075Z"
      }]
    }
  }
}
```

> `data.file.id` 就是建图例要用的 `file_id`。
> COS 图片 URL **7 天有效**（`url_expired_time`）。

### 8.2 创建图例助记（App 私有，必须签名）

```http
POST https://backup.maimemostatus.com/api/v1/notes?voc_id=<私有24hex_voc_id>
Content-Type: application/json; charset=utf-8
token: <web_token>
x-user-tag: <user_tag 首次运行自动生成>
Signature: <sha1hex>
Signature-Salt: <yyyyMMddHHmmss GMT+8>
Algorithm: MEMO_AES_V3
User-Agent: Maimemo/5.6.05_904 okhttp/4.9.2 Android/15 ...

{
  "note": {
    "type": "图例",
    "note": "",
    "publish": false,
    "files": [{"id": "6ac9c8aa163ba7766db8ccab"}]
  }
}
```

**响应：`200`**（body 为 MEMO_AES_V3 加密，需按[附录](#附录a-签名算法)解密或忽略）

> ⚠️ **字段名是 `type`**（不是开放 API 的 `note_type`）
> ⚠️ **必须带签名**：不带 → 401 `signature_missing_signature`
> ⚠️ `voc_id` 用 **24 位 hex**（App 私有），不是 `voc-...`
> ⚠️ 必须走私有域，否则 201 但**图片挂不上**

### 8.3 私有 voc_id 获取

开放 API 的 voc_id 形如 `voc-JVJBtoVTKs3Bt5B7AG...`，App 私有域需要 **24 位 hex**，如 `57067b78a172044907c607fa`。

**两者不通用，且无法从开放 voc_id 推导**（不是 hash、不是截取，是另一套自增 ObjectId）。

**途径 A（推荐，无需抓包）：私有域按拼写反查**

私有域存在 `/api/v1/vocabulary/search` 端点，可直接按 `spelling` 查询：

```bash
GET https://backup.maimemostatus.com/api/v1/vocabulary/search?spelling=sleep
# 需带 Signature / Signature-Salt / Algorithm / token / x-user-tag 头
```

- 返回 **HTTP 200**，body 是 `MEMO_AES_V3` 加密的 ASCII hex
- 已知样板：`sleep` → `57067b98a172044907c61334`，`button` → `57067b78a172044907c607fa`

> ⚠️ 响应用 `MEMO_AES_V3` 加密，目前**尚未打通解密**（见 `references/crypto.md`）。
> 密钥派生公式已 100% 验证（对 `ea` 加密 5/5 round-trip），但服务端响应疑似使用了
> 另一个 seed，仍在排查。**在解密打通前，此途径还不能落成自动化。**

**途径 B（当前可用）：App 抓包**

1. 打开墨墨 App → 进入目标词的详情页（停留 1-2 秒）
2. 抓包筛选域名 `backup.maimemostatus.com`，或直接搜请求路径
3. 找这两类请求之一，URL query 里的 `voc_id` 就是它：
   - `GET /api/v1/notes?voc_id=<24hex>`
   - `GET /api/v2/notes?voc_id=<24hex>`
4. 复制那 24 位 hex

```bash
# 拿到后立刻登记进缓存，以后同词复用
python scripts/momo.py set-voc --word sleep --voc 57067b78a172044907c607fa
python scripts/momo.py voc-cache          # 查看已登记
```

> 💡 缓存文件：`scripts/cfg/voc_private.json`（`{word: "24hex"}` 结构）
> 💡 每次抓包都会顺手存一个词，攒起来后常用词就不必再抓
> 💡 临时用也可以不登记，直接 `image-note --private-voc <24hex>`

---

## 9. 完整调用示例

### 9.1 写入释义 + 例句（纯开放 API）

```python
import json, urllib.request

TOKEN = json.load(open(r"scripts/cfg/token.json"))["open_token"]["open_token"]
BASE = "https://open.maimemo.com/open/api/v1/memo"
VOC  = "voc-JVJBtoVTKs3Bt5B7AGMiur32FgTZGbJgJtADJwLZvL85xVR3314b5LecLJx6R0SI"

def post(path, body):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST")
    r.add_header("Authorization", "Bearer " + TOKEN)
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r) as x:
        return x.status, json.loads(x.read())

# 版释义
print(post("/interpretations", {"interpretation": {
    "voc_id": VOC, "interpretation": "n. 按钮；纽扣", "tags": ["考研"], "status": "PUBLISHED"}}))

# 版例句
print(post("/phrases", {"phrase": {
    "voc_id": VOC, "phrase": "Push the button to start.",
    "interpretation": "按下按钮启动。", "tags": ["考研"], "origin": ""}}))
```

### 9.2 写入图片助记（私有上传 + 私有建卡）

见 `scripts/momo.py image-note`（可直接运行）。

---

## 10. 注意事项与踩坑

### 10.1 路径前缀

```
✅ https://open.maimemo.com/open/api/v1/memo/{vocabulary,interpretations,phrases,notes,notepads}
❌ https://open.maimemo.com/open/api/v1/notes          ← 漏了 memo 段
❌ https://open.maimemo.com/open/v1/notes              ← 漏了 api 段
```

### 10.2 三类资源互不相同

| 资源 | 说明 | 是否独立 |
|---|---|---|
| 释义 | 中文解释 | ✅ 独立资源，独立 id |
| 例句 | 句子 + 翻译 | ✅ 独立资源，独立 id |
| 助记 | 记忆法（文本/图片） | ✅ 独立资源，独立 id |

**不要把释义/例句当成助记写。**

### 10.3 图片助记必须走私有域

| 场景 | 域 | 字段名 | 签名 | 图片能挂上 |
|---|---|---|---|---|
| 文本助记 | 开放 API | `note_type` | ❌ | N/A |
| **图例助记** | **私有 API** | **`type`** | ✅ **必须** | ✅ |
| 图片上传 | 私有 API | multipart | ❌ | — |

### 10.4 删除方式不统一

| 资源 | 删除方式 |
|---|---|
| 释义 | `DELETE /memo/interpretations/{id}` |
| 例句 | `DELETE /memo/phrases/{id}` |
| 助记 | `POST /memo/notes/{id}` + `{"note":{...,"status":"DELETED"}}` |

> 助记**不能**用 `DELETE`。

### 10.5 请求体嵌套

- 创建：`{"interpretation": {...}}` / `{"phrase": {...}}` / `{"note": {...}}`
- 更新：顶层还要加 `id`（释义/例句）；助记不用
- 助记更新/删除：`note` 必须是对象，平铺会 400

### 10.6 编码与环境

- **gzip 响应**：私有域响应若带 `Content-Encoding: gzip`，**必须解压**，否则错误信息是乱码。
- **MEMO_AES_V3**：私有域部分响应加密（如 `/api/v2/notes`），解密 key 未知。**建/删操作不依赖解密**，仅在需要读私有列表时受影响。
- **multipart**：上传接口 8 个字段缺一不可，`Content-Length` 建议带上。

### 10.7 频率与配额

- 每天创建上限 **600 条**（释义 + 例句 + 助记合计）
- 10s/20 次、60s/40 次、5h/2000 次
- 批量写入时要限速

### 10.8 单资源数量上限（实测）

| 资源 | 同词上限 | 超限错误码 |
|---|---|---|
| 释义 `interpretations` | 建议 1 条（第 2 条起返回限制错误） | `interpretation_create_limitation` |
| 例句 `phrases` | 可多条 | — |
| 助记·图例 `notes[图例]` | **1 条** | `note_create_limitation` |
| 助记·文本 `notes[其他/谐音]` | **2 条** | `note_create_limitation` |

> ⚠️ `xxx_create_limitation`（超出最大创建数量限制）**≠** 标签无效。
> 前者是单词维度配额，后者是 `xxx_invalid_tag`。排查时先看错误码。

### 10.9 内容校验

- **例句** 必须**至少含 2 个单词**，否则 `400 phrase_single_voc`。
- **例句 tags** 会被系统追加 `ext:mod:quality` 等标签，属正常现象。
- **标签白名单**按资源分开（详见 [3.5](#35-tags-白名单实测)），无效返回 `xxx_invalid_tag`。

---

## 附录 A：签名算法

仅 App 私有域写入接口（`POST /api/v1/notes`）需要。

```python
import hashlib, time

TABLE32 = "C1f4134a5ac96450dbb7fe64f166a131"

def sha1hex(s):
    return hashlib.sha1(s.encode() if isinstance(s, str) else s).hexdigest()

def _jval(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return str(v)
    return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'

def p2(m):
    """dict -> [{"key":value},...]，按 key 排序；bool 不加引号"""
    if not m: return '[]'
    parts = []
    for k in sorted(m.keys()):
        v = m[k]
        if isinstance(v, dict): vs = p2(v)
        elif isinstance(v, (list, tuple)):
            vs = '[' + ','.join(p2(x) if isinstance(x, dict) else _jval(x) for x in v) + ']' if v else '[]'
        else: vs = _jval(v)
        parts.append('{"' + str(k) + '":' + vs + '}')
    return '[' + ','.join(parts) + ']'

def make_signature(token, body, query):
    salt = sha1hex(time.strftime('%Y%m%d%H%M%S', time.gmtime(time.time() + 8 * 3600)))
    d = {str(k): (v if isinstance(v, str) else str(v)) for k, v in (query or {}).items()}
    sig = sha1hex(token + salt + p2(body or {}) + p2(d) + TABLE32)
    return sig, salt
```

**要点：**
- `salt` = 当前时间 `yyyyMMddHHmmss`（GMT+8）的 SHA1
- `body` 为 `{}` 时 `p2` 返回 `[]`
- **布尔值必须是 `true`/`false` 字面量**，不能变成字符串 `"false"`

---

## 附录 B：关键 ID 速查

### 账号与设备

| 项 | 值 |
|---|---|
| 用户账号 | `<你的用户ID>` |
| x-user-tag | `<user_tag 首次运行自动生成>` |
| button 开放 voc_id | `voc-JVJBtoVTKs3Bt5B7AGMiur32FgTZGbJgJtADJwLZvL85xVR3314b5LecLJx6R0SI` |
| button 私有 voc_id | `57067b78a172044907c607fa` |
| App 版本 | `5.6.05_904` |
| 设备 | 任意 Android 机型（UA 中的设备段不影响签名） |

### button 当前内容（2026-10-10 实测基线）

**释义（1 条）**

| 内容 | tags | status |
|---|---|---|
| `n. 按钮；纽扣\nv. 扣上` | `["简明"]` | PUBLISHED |

**例句（1 条）**

| 内容 | 翻译 | origin | tags |
|---|---|---|---|
| `Click the button to confirm your choice.` | 点击按钮确认你的选择。 | `大肥鱼创建` | `["小学","ext:mod:quality"]` |

**助记（3 条）**

| note_type | 内容 | status |
|---|---|---|
| `其他` | 联想：button = but（但是）+ ton（吨）… | PUBLISHED |
| `谐音` | 谐音：'拔藤' —— 拔起藤蔓… | PUBLISHED |
| `图例` | （图片 `测试_button.png`，318×180） | UNPUBLISHED |

---

## 附录 C：更新日志

| 日期 | 变更 |
|---|---|
| 2026-10-10 | 初版；补充 tags 白名单实测（学段/风格类）、`origin` 来源标签、`phrase_single_voc` 限制、助记数量上限 |
| 2026-10-10 | 8.3 节重写：明确私有 voc_id 无法从开放 voc_id 推导，唯一途径是 App 抓包；新增 `set-voc` / `voc-cache` 缓存管理 |
| 2026-10-10 | 8.3 新增「途径 A：`/api/v1/vocabulary/search` 按拼写反查」；附 `MEMO_AES_V3` 密钥派生逆向结论（见 `references/crypto.md`） |



## 附录 D：学习计划接口（公测）

### D.1 加入学习计划
```
POST https://open.maimemo.com/open/api/v1/memo/study/add_words
Authorization: Bearer <open_token>
body: {"words": [{"id": "<开放 voc_id>"}], "advance": false}   # 单次≤1000
→ 200 {"data": {"added_count": N}}    # 单词上限不足或已添加过会影响 N
```

### D.2 提前复习
```
POST /api/v1/memo/study/advance_study
body: {"voc_ids": ["<开放 voc_id>", ...]}   # ≤1000
→ 200 {"data": {"advanced_count": N}}   # 未加入学习计划的词不计入；账号需 10 级
```

> 公测接口不保证可用性，需在 App 内开启「自动同步」。
> skill 内对应命令：`study-add --words ... [--advance]` / `study-advance --words ...`。
