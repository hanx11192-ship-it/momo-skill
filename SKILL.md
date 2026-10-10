---
name: momo-voca-recorder
description: 墨墨记单词。用于把单词的释义、例句、助记（文字或图片）写入墨墨背单词 App。当用户提到"墨墨""墨墨背单词""记到墨墨""存到墨墨""加到墨墨""墨墨助记/释义/例句""墨墨记单词"，或要求解释单词后写入墨墨时，必须使用本技能。也适用于查询单词在墨墨中已有的释义/例句/助记。
agent_created: true
---

# 墨墨记单词

把单词的**释义、例句、助记**（文字或图片）写入墨墨背单词 App，供用户随时复习。

## 核心工作流

用户典型请求：

> "帮我解释一下 button 这个词，看着 OK 的话就加到墨墨里"

执行步骤：

1. **解释单词**：用通用知识给出释义 / 例句 / 助记建议，呈现给用户确认。
2. **用户确认后写入**：调用 `scripts/momo.py` 写入墨墨。
3. **回读验证**：写入后执行 `list` 确认内容已正确保存。

> 除非用户明确要求"直接写入"，否则**先解释、等确认、再写入**。

## 环境准备

脚本依赖同目录凭证（默认 `scripts/cfg`，可用环境变量 `MAIMEMO_CONFIG_DIR` 覆盖）：

| 文件 | 内容 | 获取方式 |
|---|---|---|
| `token.json` | `open_token`（24h）+ `web_token`（约1年） | 运行 `open_token.py` / `web_token.py` |
| `cof.json` | 账号密码 | 用户提供（复制 `cof.example.json` 改） |
| `config.json` | 内容默认偏好：释义/例句的 tags、来源、公开性 | 可选（复制 `config.example.json`，不建走内置默认） |

**写入前先检查凭证**：

```bash
python scripts/momo.py whoami
```

若提示 token 过期，指导用户重新运行对应获取脚本。

## 三类内容（互不相同，不要混淆）

| 资源 | 说明 | App 中的位置 |
|---|---|---|
| **释义** interpretation | 中文解释，如 `n. 按钮；纽扣` | 释义区 |
| **例句** phrase | 英文句子 + 中文翻译 | 例句区 |
| **助记** note | 记忆法，文字或图片 | 助记区 |

> 释义和例句**不是**助记，各有独立接口。

## 常用命令

**查询词条**

```bash
python scripts/momo.py vocab button
python scripts/momo.py list button              # 列出释义/例句/助记
python scripts/momo.py list button --type note  # 只看助记
```

**超上限时的询问/替换流程（释义/例句/助记/图例通用）**

创建返回 `xxx_create_limitation`（超出数量上限）时，脚本会列出该词已有的条目
（含 id / tags / 内容预览）并以**退出码 3** 结束。此时应把列表展示给用户并询问
「替换其中一条，还是放弃」；用户选定后重跑同一命令加 `--replace <id>`（先删旧再建新）。
禁止在没有用户确认的情况下擅自删除已有内容。

**写入释义**

```bash
python scripts/momo.py interp-add --word button \
  --text "n. 按钮；纽扣。v. 扣上."
# 默认公开 + tags 取 config.json（默认 简明）；tags 可多选；--private 改私有
```

**写入例句**

```bash
python scripts/momo.py phrase-add --word button \
  --phrase "Click the button to confirm your choice." \
  --interp "点击按钮确认你的选择。"
# 默认公开 + tags 取 config.json（默认 小学）+ 来源取 config.json 的 phrase.origin；
# tags 可多选（--tags 小学 四级），--private 改私有
```

**写入文字助记**

```bash
python scripts/momo.py note-add --word button \
  --type 其他 --text "联想：but（但是）+ ton（吨）→ 一吨按钮？其实是小小按钮。" \
  --publish
```

**写入图片助记（图例）**

```bash
# 首次需先登记该词的私有 voc_id（见下方「图片助记前置条件」）
python scripts/momo.py set-voc --word button --voc 57067b78a172044907c607fa
python scripts/momo.py image-note --word button --image "图片路径.png"
```

**私有 voc_id 缓存管理**

```bash
python scripts/momo.py set-voc --word sleep --voc <24hex>   # 登记
python scripts/momo.py voc-cache                            # 查看全部
```

**删除**

```bash
python scripts/momo.py interp-del --id intp-xxx
python scripts/momo.py phrase-del --id ph-xxx
python scripts/momo.py note-del --id nt-xxx --note-type 其他
```

## 关键约束（必须遵守）

### 1. 标签白名单（非白名单会 400）

| 资源 | 可用标签 |
|---|---|
| 通用（释义/例句） | `考研` `四级` `六级` `雅思` `托福` `GRE` `专四` `专八` |
| 例句专用 | `小学` `初中` `高中` |
| 释义风格 | `简明` `详细` |

- 无效标签报 `xxx_invalid_tag`；**不要用** `高考` `牛津` `柯林斯` `API测试` 等。
- 释义/例句的 `tags` **可选**，不确定时用 `考研`。

### 2. 数量上限（超出报 `xxx_create_limitation`）

| 资源 | 同词上限 |
|---|---|
| 释义 | 1 条 |
| 助记·图例 | 1 条 |
| 助记·文本 | **2 条** |
| 例句 | 可多条 |

> 想表达多段内容时，优先用**释义 + 例句**，而非堆助记。

### 3. 例句必须至少 2 个单词

否则 400 `phrase_single_voc`。单词本身不能当例句。

### 4. 图片助记必须走 App 私有域

`image-note` 命令已自动处理（上传 + 私有接口建图例 + 签名）。
**注意**：开放 API 建图例会返回成功但**图片挂不上**，不要用开放 API 建图例。

### 5. 助记删除方式特殊

助记用 `POST + status:DELETED` 软删除，**不能用 HTTP DELETE**。
删除时必须传**原 `note_type`**（`图例`/`其他`/`谐音`），否则报 `note_not_found`。
脚本已封装，直接用 `note-del` 即可。

### 6. 图片助记需要私有 voc_id

开放 voc_id 形如 `voc-JVJBtoVTK...`（长串），私有 voc_id 是 **24 位小写 hex**（如 `57067b78a172044907c607fa`）。

**二者不通用，且无法从开放 voc_id 推导**——不是 hash、不是截取，是另一套自增 ObjectId。

#### 获取途径

**途径 A（✅ 已打通，首选）：内置离线索引，零设备依赖**

skill 已内置 `references/voc_index.json.gz`（**128,683 个单词 → 私有 voc_id**，
2026-10-10 从 App 本地库全量导出）。查询纯本地、约 0.2 秒，**不需要手机**。
真机校验：`button -> 57067b78a172044907c607fa`（与抓包值一致）。

```bash
python scripts/voc_db.py button sleep    # 秒回
```

`momo.py` 的 `image-note` 已自动集成：查缓存 → 查内置索引 → 建图例，
全程无感。仅当索引查不到生僻词时，才降级走 adb 读手机实时库（需 root），
或最后向用户索要抓包 24hex。

索引刷新（可选，词库版本过旧时）：

```bash
python scripts/voc_db.py --pull          # 从手机重新拉库（需 USB + root）
```

**途径 B：私有域按拼写反查（解密未打通）**

私有域存在 `GET /api/v1/vocabulary/search?spelling=<word>`（HTTP 200），返回加密的
`MEMO_AES_V3` 数据。签名链正确且被服务端接受（HTTP 200），
但**响应体无法离线解密**（11/11 样本失败，native `da()` 亦返回 NULL，
seed 无法复现，详见 `references/crypto.md` 第 7 节）。此途径当前不可用。

逆向现状（详见 `references/crypto.md`）：

| 环节 | 状态 |
|---|---|
| 签名算法 `SHA1(token+salt+p2(body)+p2(query)+CONST)` | ✅ 反汇编确认 |
| native `e()` 自定义编码（纯 Python 15/15 逐字节复现） | ✅ |
| key/iv 派生 `sha256(e(seed))[0:32]/[32:48]` | ✅ hook 实测一致 |
| native `ea` ↔ `da` 往返 | ✅ 5/5 PASS |
| 解密服务端实况响应 | ❌ seed 无法离线复现（已绕过） |

**途径 C：App 抓包（兜底）**

#### 图片助记前置条件（必须向用户索要）

写好图例前，先检查缓存：

```bash
python scripts/momo.py voc-cache          # 看这个词是否已在缓存里
```

**若缓存里没有**，直接跑 `image-note` —— 它会自动经 adb 读 App 本地库反查
（需手机 USB 连接 + root）。只有自动查询也失败时，才按下方话术向用户索要。

> 图片助记需要一个 24 位 hex 的私有 voc_id，它和开放 API 返回的长串 voc_id 不通用，只能从 App 抓包拿到。麻烦你：
> 1. 打开墨墨 App → 进入 **<词>** 的详情页
> 2. 抓包筛选 `backup.maimemostatus.com`，找 `?voc_id=<24hex>` 的请求
> 3. 把那 24 位 hex 发我
>
> 拿到后我一条命令就能把图挂上去。

用户给出 hex 后，先 `set-voc` 存进缓存，再跑 `image-note`：

```bash
python scripts/momo.py set-voc --word <词> --voc <24hex>
python scripts/momo.py image-note --word <词> --image "图片路径.png"
```

> 缓存文件 `scripts/cfg/voc_private.json`，结构 `{word: "24hex"}`。攒起来后同词复用，不必反复抓包。

## 典型场景示例

### 场景 A：完整写入一个词

用户："帮我记住 button 这个词"

```bash
# 1. 确认词条存在
python scripts/momo.py vocab button

# 2. 写入释义
python scripts/momo.py interp-add --word button --text "n. 按钮；纽扣"

# 3. 写入例句
python scripts/momo.py phrase-add --word button \
  --phrase "Click the button to start." --interp "点击按钮开始。"

# 4. 写入助记
python scripts/momo.py note-add --word button --type 谐音 \
  --text "谐音'拔藤'：拔开藤蔓，露出按钮。" --publish

# 5. 验证
python scripts/momo.py list button
```

### 场景 B：先解释，用户确认再写入

1. 输出释义 / 例句 / 助记建议草案。
2. 等用户确认或修改。
3. 按场景 A 执行写入。

### 场景 C：带图片的助记

1. 用户提供图片路径。
2. 先 `voc-cache` 查该词的私有 voc_id 是否已登记。
3. 未登记 → 按「图片助记前置条件」向用户索要 24hex，收到后 `set-voc`。
4. 执行 `image-note`。
5. 提示用户在 App 中确认图片显示（API 无法回读图片字段）。

## 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `401 user_unauthorized` | token 失效，重跑获取脚本 |
| `xxx_invalid_tag` | 标签不在白名单，换成 `考研` 等 |
| `xxx_create_limitation` | 达到数量上限，改用释义/例句 |
| `phrase_single_voc` | 例句单词数 < 2 |
| `note_not_found` | 删除时 note_type 与原值不一致 |
| 图例创建成功但无图 | 走错了域，必须用 `image-note`（私有域） |
| 提示缺私有 voc_id | 自动查库失败（手机未连/无 root/App 未登录）；请用户抓包给 24hex，再 `set-voc` 登记 |

## 参考文档

- 完整接口文档（请求头 / 请求体 / 响应体 / 全部踩坑）：`references/api.md`
- 脚本源码：`scripts/momo.py`
