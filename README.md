# 墨墨记单词 (maimemo-vocab-writer)

一个 [WorkBuddy](https://www.workbuddy.cn) skill：让 AI 解释单词，你确认后把**释义 / 例句 / 助记（文字或图片）**一键写入墨墨背单词 App，供随时复习。

```
你：帮我解释一下 button 这个词，看着 OK 就加到墨墨里
AI：（给出释义 / 例句 / 谐音助记）
你：可以
AI：（自动写入墨墨 App ✓）
```

## 特性

- **全自动私有 voc_id 解析**：内置 129,927 词离线词库（`voc_index.json.gz` + `voc_wordlib.db`），查询 0.2 秒、零设备依赖；查不到的生僻词可自动降级经 adb(root) 从手机实时拉库。
- **文字助记**：释义（简明/详细）、例句（可带来源标签）、谐音/其他助记，走墨墨开放 API。
- **图片助记（图例）**：自动上传图片并创建 App 内私有图例，走 App 私有协议（本项目逆向实现的签名算法）。
- **凭证全自动**：`open_token.py`（24h 开放 API token）与 `web_token.py`（约 1 年私有域 token）读同一份 `cof.json`，自动获取、自动续期，无需抓包。

## 目录结构

```
maimemo-vocab-writer/
├── SKILL.md                      # skill 说明（WorkBuddy 读取的入口）
├── LICENSE                       # MIT
├── references/
│   ├── api.md                    # 接口参考（开放 API + App 私有协议）
│   ├── crypto.md                 # libmomoco.so 签名/加密算法逆向笔记
│   ├── voc_index.json.gz         # 128,683 词 → 私有 voc_id 离线索引
│   └── voc_wordlib.db            # 129,927 词完整词表 SQLite（仅 VOC_TB，无账号数据）
└── scripts/
    ├── maimemo.py                # 核心客户端（释义/例句/助记/图片上传）
    ├── open_token.py             # 开放 API token 自动获取（OAuth2 流程复刻）
    ├── web_token.py              # 私有域 web_token 自动获取
    ├── voc_db.py                 # 私有 voc_id 四级查询（索引→内置库→缓存→adb）
    ├── memo_crypto.py            # MEMO_AES_V3 算法研究（native 仿真 + 纯 Python e()）
    ├── elf.py                    # ELF/JNI 表解析工具
    ├── libmomoco.so              # 墨墨 native 库（仿真宿主用）
    └── cfg/                      # 凭证目录（token.example.json / cof.example.json 模板）
```

## 快速开始

1. **配置凭证**（只需一次）：

   ```bash
   cd scripts/cfg
   cp cof.example.json cof.json
   # 编辑 cof.json，填入你的墨墨账号（邮箱）和密码
   ```

2. **获取 token**（自动写入 `scripts/cfg/token.json`）：

   ```bash
   python scripts/open_token.py     # 开放 API token，24h 有效，可随时重跑续期
   python scripts/web_token.py      # 私有域 token，约 1 年有效
   ```

   > 默认凭证目录为 `scripts/cfg/`，可用环境变量 `MAIMEMO_CONFIG_DIR` 指向其他位置。

3. **使用**：在 WorkBuddy 里说「帮我解释 XX 这个词，OK 的话加到墨墨里」即可；也可直接命令行：

   ```bash
   python scripts/maimemo.py define --word button --text "n. 按钮" --tags 简明
   python scripts/maimemo.py phrase  --word button --phrase "Push the button." --interp "按下按钮"
   python scripts/maimemo.py note    --word button --type 谐音 --text "不疼（button）"
   python scripts/maimemo.py image-note --word button --image 图片路径.png
   ```

## 技术细节（为什么能全自动）

- **私有 voc_id**：开放 API 的 `voc-...` ID 与 App 私有协议的 24hex `voc_id` 不通用且无法推导。本 skill 内置了从墨墨 App 本地数据库（`momo.v425.db` 的 `VOC_TB`，129,927 词）导出的映射，离线即可反查。
- **App 私有协议签名**：`Signature = SHA1hex(token + salt + p2(body) + p2(query) + TABLE32)`，`salt = SHA1hex(yyyyMMddHHmmss GMT+8)`，全部本地计算，详见 `references/crypto.md`。
- **图例助记必须走私有域**：开放 API 建图例会 201 成功但图片挂不上（私有 file_id 无法关联），这是踩过两次的坑，skill 已内置正确路由。

## 免责声明

本项目仅供个人学习与自动化效率研究，通过逆向实现了墨墨背单词客户端协议的本地调用。请勿用于任何商业用途或批量滥用（墨墨开放 API 有频控与每日创建上限）。使用本项目产生的一切后果由使用者自行承担。如侵犯到墨墨官方权益，请联系删除。
