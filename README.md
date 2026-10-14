# momo-voca-recorder

一个 AI skill + 命令行工具：让 AI 解释单词，你确认后把**释义 / 例句 / 助记（文字或图片）**一键写入 momo（背单词 App），支持加入到学习计划/提前复习。

**不绑定特定平台**——既可作为 WorkBuddy / Claude 等 AI Agent 的 skill 使用，也可以直接当纯命令行工具用，任何能跑 Python 的地方都行。

```
你：帮我解释一下 button 这个词，看着 OK 就加到 momo 里
AI：（给出释义 / 例句 / 谐音助记）
你：可以
AI：（自动写入 App ✓）
```

## 特性

- **全自动私有 voc_id 解析**：内置 128,683 词离线索引（`voc_index.tsv`，覆盖 App 词表全部唯一拼写），查询 0.2 秒、零设备依赖；查不到的生僻词可自动降级经 adb(root) 从手机实时拉库。
- **文字内容**：释义（多标签）、例句（多标签 + 来源标签）、谐音/其他助记，走开放 API。
- **图片助记（图例）**：自动上传图片并创建 App 内私有图例（图例一律私有，仅自己可见），走 App 私有协议（本项目逆向实现的签名算法）。
- **图片格式转换**：内置 `convert-image` 命令，webp / bmp / gif / tiff / avif 一键转 png/jpg；`image-note` 上传前也会自动转换，无需手动处理。
- **学习计划**：`study-add` 把单词加入学习计划（可一并提前复习），自动批量查词，单次≤1000 词；走官方公测接口 `study/add_words`。
- **凭证全自动**：`open_token.py`（24h 开放 API token）与 `web_token.py`（约 1 年私有域 token）读同一份 `cof.json`。**token 缺失或过期时，核心脚本会自动调用它们续期**——配置好账号后，无论是人还是 AI 驱动的 skill，都不需要任何手动维护。

## 目录结构

```
momo-voca-recorder/
├── SKILL.md                      # skill 说明（AI Agent 读取的入口）
├── LICENSE                       # MIT
├── references/
│   ├── api.md                    # 接口参考（开放 API + App 私有协议）
│   ├── crypto.md                 # 签名/加密算法逆向笔记
│   ├── voc_index.tsv         # 128,683 词 → 私有 voc_id 离线索引
│   └── voc_wordlib.db            # 129,927 词完整词表 SQLite（仅词表，无账号数据）
└── scripts/
    ├── momo.py                # 核心客户端（释义/例句/助记/图片上传）
    ├── open_token.py             # 开放 API token 自动获取（OAuth2 流程复刻）
    ├── web_token.py              # 私有域 web_token 自动获取
    ├── voc_db.py                 # 私有 voc_id 四级查询（索引→内置库→缓存→adb）
    └── cfg/                      # 凭证与配置目录（各 *.example.json 为模板）
```

## 快速开始

### 第 1 步：配置账号（只需一次）

```bash
cd scripts/cfg
cp cof.example.json cof.json
cp config.example.json config.json   # 可选
```

然后用任意文本编辑器打开 **`cof.json`**，填入你自己的 App 登录账号：

```json
{
  "account": "你的登录邮箱",
  "password": "你的登录密码"
}
```

> ⚠️ `cof.json` 含明文密码，请勿提交到 git / 分享给他人（本仓库默认不含此文件）。

**`config.json`** 是内容默认偏好，可按需修改（不建也能用，走内置默认）：

```json
{
  "interp": { "tags": ["简明"], "public": true },
  "phrase": { "tags": ["小学"], "origin": "github.com/hanx11192-ship-it/momo-skill 项目创建", "public": true },
  "note":   { "type": "其他", "public": false }
}
```

| 键 | 含义 | 默认 |
|---|---|---|
| `interp.tags` | 释义标签（可多选数组） | `["简明"]` |
| `interp.public` | 释义是否公开 | `true` |
| `phrase.tags` | 例句标签（可多选数组） | `["小学"]` |
| `phrase.origin` | 例句「来源」标签（App 内显示的自由文本） | `github.com/hanx11192-ship-it/momo-skill 项目创建` |
| `phrase.public` | 例句是否公开 | `true` |
| `note.type` | 文本助记类型 | `其他`（可选 谐音） |
| `note.public` | 文本助记是否公开 | `false`（默认私有） |

标签以 **momo App 内实际提供的标签为准**，以下为实测可用值：例句/释义通用 `考研 四级 六级 雅思 托福 GRE 专四 专八`；例句学段类 `小学 初中 高中`；释义风格 `简明 详细`。使用 App 内不存在于服务端白名单的标签会被拒绝。

### 第 2 步：token（全自动，无需手动维护）

```bash
python scripts/open_token.py     # 可手动执行；24h 有效
python scripts/web_token.py      # 可手动执行；约 1 年有效
```

- 两个脚本读取 `scripts/cfg/cof.json`，结果自动写入 `scripts/cfg/token.json`。
- **通常不需要手动跑**：`momo.py` 检测到 token 缺失或过期时会自动调用这两个脚本续期。对 AI Agent 场景，skill 只管正常调用写入命令，续期在后台自动完成。
- 默认凭证目录为 `scripts/cfg/`，可用环境变量 `MAIMEMO_CONFIG_DIR` 指向其他位置。

### 第 3 步：使用

```bash
python scripts/momo.py interp-add --word button --text "n. 按钮"          # 释义，默认公开+简明
python scripts/momo.py phrase-add --word button --phrase "Push the button." --interp "按下按钮"   # 例句，默认公开+小学+配置来源
python scripts/momo.py note-add   --word button --text "不疼（button）"    # 文本助记，默认私有+其他
python scripts/momo.py image-note --word button --image 图片.webp             # 图片助记，webp 自动转 png
python scripts/momo.py study-add --word button --advance                      # 加入学习计划并提前到当下复习
python scripts/momo.py convert-image --src 截图.webp --fmt jpg                # 单独转换格式
```

- tags 均支持多选：`--tags 简明 详细`、`--tags 小学 四级`。
- **超上限自动进入询问流程**：某类内容达到数量上限（释义 1 条/词、例句若干、文本助记 2 条、图例 1 条）时，
  脚本列出已有条目并以退出码 3 结束，由 AI 展示给用户决定是否替换；确认后加 `--replace <id>` 先删后建。
- 释义/例句默认公开，加 `--private` 改私有；文本助记默认私有，加 `--publish` 改公开。
- **图片助记（图例）一律为私有**——这是 App 图例的默认形态，上传后仅你自己可见。

## 技术细节（为什么能全自动）

- **私有 voc_id**：开放 API 的 `voc-...` ID 与 App 私有协议的 24hex `voc_id` 不通用且无法推导。本 skill 内置了从 App 本地数据库（`momo.v425.db` 的 `VOC_TB`）导出的映射（128,683 个唯一拼写），离线即可反查。
- **App 私有协议签名**：`Signature = SHA1hex(token + salt + p2(body) + p2(query) + TABLE32)`，`salt = SHA1hex(yyyyMMddHHmmss GMT+8)`，全部本地计算，详见 `references/crypto.md`。
- **图例助记必须走私有域**：开放 API 建图例会 201 成功但图片挂不上（私有 file_id 无法关联），这是踩过两次的坑，skill 已内置正确路由。

## 免责声明

本项目仅供个人学习与自动化效率研究，通过逆向实现了背单词 App 客户端协议的本地调用。请勿用于任何商业用途或批量滥用（开放 API 有频控与每日创建上限）。使用本项目产生的一切后果由使用者自行承担。如侵犯到相关官方权益，请联系删除。
