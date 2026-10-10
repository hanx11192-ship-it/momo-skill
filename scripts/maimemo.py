#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
墨墨记单词 — 核心客户端

统一封装墨墨开放 API（释义/例句/助记/词条）与 App 私有域（图片上传 + 图例助记）。
所有接口均经实测验证（2026-10-10）。

用法：
  python maimemo.py vocab button
  python maimemo.py list button [--type all|interp|phrase|note]
  python maimemo.py interp-add --word button --text "n. 按钮" [--tags 考研] [--public]
  python maimemo.py interp-del --id intp-xxx
  python maimemo.py phrase-add --word button --phrase "Click the button." --interp "点击按钮。" \
                               [--tags 小学] [--origin "大肥鱼创建"] [--public]
  python maimemo.py phrase-del --id ph-xxx
  python maimemo.py note-add --word button --type 其他 --text "联想..." [--publish]
  python maimemo.py note-del --id nt-xxx --note-type 其他
  python maimemo.py image-note --word button --image E:\\path\\pic.png [--private-voc 57067b...]
  python maimemo.py whoami
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ────────────────────────── 配置 ──────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
CFG_DIR = os.environ.get("MAIMEMO_CONFIG_DIR", os.path.join(_HERE, "cfg"))
TOKEN_FILE = os.path.join(CFG_DIR, "token.json")
COF_FILE = os.path.join(CFG_DIR, "cof.json")

OPEN_BASE = "https://open.maimemo.com/open/api/v1/memo"
PRIV_HOST = "https://backup.maimemostatus.com"
TABLE32 = "C1f4134a5ac96450dbb7fe64f166a131"

def _user_tag():
    """x-user-tag：32hex 用户标识。优先环境变量，否则首次运行自动生成并持久化。"""
    env = os.environ.get("MAIMEMO_USER_TAG")
    if env:
        return env
    p = os.path.join(CFG_DIR, "user_tag")
    try:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t
        os.makedirs(CFG_DIR, exist_ok=True)
        t = uuid.uuid4().hex
        with open(p, "w", encoding="utf-8") as f:
            f.write(t)
        return t
    except Exception:
        return uuid.uuid4().hex

USER_TAG = _user_tag()
UA = ("Maimemo/5.6.05_904 okhttp/4.9.2 Android/15 Channel/Vivo CustomOS/ColorOS (15.0.0.840) "
      "Device/Android+Phone (arm64)")

# 标签白名单（实测 2026-10-10）
TAGS_COMMON = ["考研", "四级", "六级", "雅思", "托福", "GRE", "专四", "专八"]
TAGS_PHRASE = TAGS_COMMON + ["小学", "初中", "高中"]
TAGS_INTERP = TAGS_COMMON + ["简明", "详细"]

NOTE_TYPES_TEXT = ["其他", "谐音"]

# 私有 voc_id 缓存文件（word -> 24hex）
PRIV_VOC_CACHE = os.path.join(CFG_DIR, "voc_private.json")


# ────────────────────────── 工具 ──────────────────────────

def die(msg, code=1):
    print("❌ " + msg, file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print("✅ " + msg)


def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        die(f"找不到 {TOKEN_FILE}。请先运行 open_token.py 与 web_token.py 获取凭证。")
    with open(TOKEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def open_token():
    t = load_tokens().get("open_token", {})
    tok = t.get("open_token")
    if not tok:
        die("token.json 中缺少 open_token。请运行 open_token.py。")
    exp = t.get("expire_ts")
    if exp and time.time() > exp:
        die(f"open_token 已过期（{t.get('expire')}）。请重新运行 open_token.py。")
    return tok


def web_token():
    t = load_tokens().get("web_token", {})
    tok = t.get("web_token")
    if not tok:
        die("token.json 中缺少 web_token。请运行 web_token.py。")
    exp = t.get("expire_ts")
    if exp and time.time() > exp:
        die(f"web_token 已过期（{t.get('expire')}）。请重新运行 web_token.py。")
    return tok


# ────────────────────────── HTTP ──────────────────────────

def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    return raw


def open_api(method, path, body=None, query=None):
    """开放 API 调用。返回 (status, json|text)。"""
    url = OPEN_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + open_token())
    r.add_header("Accept", "application/json")
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = _read(resp)
            return resp.status, _parse(raw)
    except urllib.error.HTTPError as e:
        raw = _read(e)
        return e.code, _parse(raw)
    except Exception as e:
        die(f"请求失败：{e}")


def _parse(raw):
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return raw.decode("utf-8", "replace")


def _sha1hex(s):
    return hashlib.sha1(s.encode() if isinstance(s, str) else s).hexdigest()


def _jval(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _p2(m):
    if not m:
        return "[]"
    parts = []
    for k in sorted(m.keys()):
        v = m[k]
        if isinstance(v, dict):
            vs = _p2(v)
        elif isinstance(v, (list, tuple)):
            vs = ("[" + ",".join(_p2(x) if isinstance(x, dict) else _jval(x) for x in v) + "]") if v else "[]"
        else:
            vs = _jval(v)
        parts.append('{"' + str(k) + '":' + vs + "}")
    return "[" + ",".join(parts) + "]"


def priv_sign(body, query):
    salt = _sha1hex(time.strftime("%Y%m%d%H%M%S", time.gmtime(time.time() + 8 * 3600)))
    d = {str(k): (v if isinstance(v, str) else str(v)) for k, v in (query or {}).items()}
    sig = _sha1hex(web_token() + salt + _p2(body or {}) + _p2(d) + TABLE32)
    return sig, salt


def priv_api(method, path, body=None, query=None, sign=True, want_sig=False):
    """App 私有域调用。

    want_sig=True 时返回 (status, body, sig, salt)，用于需要用同一份
    Signature 派生密钥解密响应的场景（sign 必须与实际发出的请求完全一致）。
    """
    url = PRIV_HOST + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("User-Agent", UA)
    r.add_header("x-user-tag", USER_TAG)
    r.add_header("token", web_token())
    r.add_header("Accept-Encoding", "gzip")
    if data:
        r.add_header("Content-Type", "application/json; charset=utf-8")
    sig = salt = None
    if sign:
        sig, salt = priv_sign(body or {}, query or {})
        r.add_header("Signature", sig)
        r.add_header("Signature-Salt", salt)
        r.add_header("Algorithm", "MEMO_AES_V3")
    st, raw = None, b""
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            st, raw = resp.status, _read(resp)
    except urllib.error.HTTPError as e:
        st, raw = e.code, _read(e)
    except Exception as e:
        die(f"请求失败：{e}")
    if want_sig:
        return st, raw, sig, salt
    return st, raw


# ────────────────────────── 词条 ──────────────────────────

def get_voc_id(spelling):
    st, j = open_api("GET", "/vocabulary", query={"spelling": spelling})
    if st != 200 or not isinstance(j, dict):
        die(f"查询 {spelling} 失败：HTTP {st} {j}")
    voc = j.get("data", {}).get("voc")
    if not voc:
        die(f"词库中找不到 {spelling}。")
    return voc["id"]


def load_priv_voc_cache():
    if os.path.exists(PRIV_VOC_CACHE):
        try:
            with open(PRIV_VOC_CACHE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_priv_voc_cache(d):
    try:
        with open(PRIV_VOC_CACHE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def put_priv_voc(word, hexid):
    """把 24hex 私有 voc_id 存进缓存。"""
    if not re.fullmatch(r"[0-9a-f]{24}", hexid or ""):
        die(f"私有 voc_id 必须是 24 位小写 hex，收到的是 {hexid!r}")
    d = load_priv_voc_cache()
    d[word] = hexid
    save_priv_voc_cache(d)
    ok(f"已缓存  {word} -> {hexid}")
    print(f"   缓存文件：{PRIV_VOC_CACHE}")


# ────────────────────────── 释义 ──────────────────────────

def interp_add(word, text, tags, public):
    voc = get_voc_id(word)
    tags = tags or ["考研"]
    bad = [t for t in tags if t not in TAGS_INTERP]
    if bad:
        print(f"⚠️  标签 {bad} 不在实测白名单内，可能被拒。可用：{TAGS_INTERP}")
    body = {"interpretation": {
        "voc_id": voc, "interpretation": text, "tags": tags,
        "status": "PUBLISHED" if public else "UNPUBLISHED"}}
    st, j = open_api("POST", "/interpretations", body)
    if st in (200, 201):
        nid = j.get("data", {}).get("interpretation", {}).get("id")
        ok(f"释义已创建 HTTP {st}  id={nid}")
    else:
        die(f"创建失败 HTTP {st}：{json.dumps(j, ensure_ascii=False)}")


def interp_del(iid):
    st, j = open_api("DELETE", f"/interpretations/{iid}")
    if st == 200:
        ok(f"释义已删除 {iid}")
    else:
        die(f"删除失败 HTTP {st}：{json.dumps(j, ensure_ascii=False)}")


# ────────────────────────── 例句 ──────────────────────────

def phrase_add(word, phrase, interp, tags, origin, public):
    voc = get_voc_id(word)
    tags = tags or ["考研"]
    bad = [t for t in tags if t not in TAGS_PHRASE]
    if bad:
        print(f"⚠️  标签 {bad} 不在实测白名单内，可能被拒。可用：{TAGS_PHRASE}")
    if len(phrase.split()) < 2:
        die("例句必须至少包含 2 个单词（phrase_single_voc 限制）。")
    body = {"phrase": {
        "voc_id": voc, "phrase": phrase, "interpretation": interp,
        "tags": tags, "origin": origin or ""}}
    st, j = open_api("POST", "/phrases", body)
    if st in (200, 201):
        nid = j.get("data", {}).get("phrase", {}).get("id")
        ok(f"例句已创建 HTTP {st}  id={nid}")
    else:
        die(f"创建失败 HTTP {st}：{json.dumps(j, ensure_ascii=False)}")


def phrase_del(pid):
    st, j = open_api("DELETE", f"/phrases/{pid}")
    if st == 200:
        ok(f"例句已删除 {pid}")
    else:
        die(f"删除失败 HTTP {st}：{json.dumps(j, ensure_ascii=False)}")


# ────────────────────────── 助记（文本） ──────────────────────────

def note_add(word, note_type, text, publish):
    voc = get_voc_id(word)
    if note_type not in NOTE_TYPES_TEXT:
        die(f"文本助记 note_type 仅支持 {NOTE_TYPES_TEXT}（图例请用 image-note 命令）。")
    body = {"note": {"voc_id": voc, "note_type": note_type, "note": text, "publish": publish}}
    st, j = open_api("POST", "/notes", body)
    if st in (200, 201):
        nid = j.get("data", {}).get("note", {}).get("id")
        ok(f"文本助记已创建 HTTP {st}  id={nid}")
    elif isinstance(j, dict) and any(e.get("code") == "note_create_limitation" for e in j.get("errors", [])):
        die("超出助记数量上限（文本类每词 2 条，图例 1 条）。改用释义/例句接口。")
    else:
        die(f"创建失败 HTTP {st}：{json.dumps(j, ensure_ascii=False)}")


def note_del(nid, note_type, text=""):
    body = {"note": {"note": text, "note_type": note_type, "status": "DELETED"}}
    st, j = open_api("POST", f"/notes/{nid}", body)
    if st in (200, 201):
        ok(f"助记已删除（软删）{nid}")
    else:
        die(f"删除失败 HTTP {st}：{json.dumps(j, ensure_ascii=False)}"
            f"\n提示：note_type 必须与原值一致（图例/其他/谐音）。")


# ────────────────────────── 图片助记 ──────────────────────────

def upload_image(path, filename=None):
    if not os.path.exists(path):
        die(f"图片不存在：{path}")
    filename = filename or os.path.basename(path)
    ctype = "image/png"
    low = filename.lower()
    if low.endswith((".jpg", ".jpeg")):
        ctype = "image/jpeg"
    elif low.endswith(".webp"):
        ctype = "image/webp"
    elif low.endswith(".gif"):
        ctype = "image/gif"
    boundary = str(uuid.uuid4())
    content = open(path, "rb").read()
    fields = [("object_class", "NOTE"), ("publish", "false"), ("app_version", "5.6.05_904"),
              ("android_version", "15"), ("device", "Phone"), ("android_channel", "vivo")]
    parts = []
    for name, val in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file_name"\r\n\r\n{filename}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f'Content-Type: {ctype}\r\n\r\n'.encode() + content + b"\r\n")
    parts.append(f'--{boundary}--\r\n'.encode())
    data = b"".join(parts)
    r = urllib.request.Request(PRIV_HOST + "/api/v1/content/files", data=data, method="POST")
    r.add_header("User-Agent", UA)
    r.add_header("x-user-tag", USER_TAG)
    r.add_header("token", web_token())
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    r.add_header("Accept-Encoding", "gzip")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = _read(resp)
            j = _parse(raw)
            if resp.status == 200 and isinstance(j, dict):
                f = j.get("data", {}).get("file", {})
                return f.get("id"), f
            die(f"上传失败 HTTP {resp.status}：{str(j)[:300]}")
    except urllib.error.HTTPError as e:
        die(f"上传失败 HTTP {e.code}：{_read(e).decode('utf-8', 'replace')[:300]}")


def try_resolve_priv_voc(word):
    """按 spelling 反查 24hex 私有 voc_id —— 读 App 本地数据库（已确认可用）。

    原理（2026-10-10 真机验证）：
      墨墨 App 会把服务端数据解密后落到本地 SQLite：
        /data/data/com.maimemo.android.momo/databases/momo.v425.db
      其中 VOC_TB 表含全部 12.9 万词条的 (id, spelling) 映射，
      id 即私有 voc_id（Mongo ObjectId）。
      实测：button -> 57067b78a172044907c607fa（与抓包中的私有 id 完全一致）。

    这条路完全绕开了 MEMO_AES_V3 响应解密（其 seed 无法离线复现），
    因此是本 skill 的推荐自动化路径。需设备开启 USB 调试并具备 root（su）。

    失败时返回 None（不抛异常）。
    """
    try:
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voc_db.py")
        if not os.path.exists(_p):
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("voc_db", _p)
        vd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vd)
        vid = vd.lookup([word]).get(word)
        if vid:
            put_priv_voc(word, vid)
            return vid
    except Exception:
        return None
    return None


def image_note(word, image_path, private_voc=None):
    # 1) 上传
    fid, finfo = upload_image(image_path)
    ok(f"图片已上传  file_id={fid}  {finfo.get('size')} bytes")
    # 2) 私有 voc_id
    pvoc = private_voc
    if not pvoc:
        cache = load_priv_voc_cache()
        pvoc = cache.get(word)
    if not pvoc:
        # 自动化路径：读 App 本地 momo.v425.db 的 VOC_TB 表反查（无需解密响应）
        pvoc = try_resolve_priv_voc(word)
    if not pvoc:
        die(f"缺少 {word} 的私有 voc_id（24hex）。\n"
            f"   自动查询失败，请确认：\n"
            f"     1) 手机已 USB 连接且 adb devices 可见；\n"
            f"     2) 设备已 root（su 可用）；\n"
            f"     3) 墨墨 App 已登录并打开过一次。\n"
            f"   也可手动指定：--private-voc <24hex>\n"
            f"   （开放 voc_id 形如 voc-xxx，与私有 24 位 hex 不同）")
    # 3) 建图例（私有域 + 签名）
    body = {"note": {"type": "图例", "note": "", "publish": False, "files": [{"id": fid}]}}
    st, raw = priv_api("POST", "/api/v1/notes", body, {"voc_id": pvoc}, sign=True)
    if st == 200:
        ok(f"图例助记已创建（私有域）HTTP {st}")
        print("   响应为 MEMO_AES_V3 加密，属正常现象。请在 App 中确认图片显示。")
    else:
        die(f"创建失败 HTTP {st}：{raw.decode('utf-8', 'replace')[:300]}")


# ────────────────────────── 查询 ──────────────────────────

def cmd_list(word, which):
    voc = get_voc_id(word)
    print(f"📖 {word}  (voc_id={voc})\n")
    mapping = [("释义", "/interpretations", "interpretations"),
               ("例句", "/phrases", "phrases"),
               ("助记", "/notes", "notes")]
    for label, path, key in mapping:
        if which not in ("all", {"释义": "interp", "例句": "phrase", "助记": "note"}[label]):
            continue
        st, j = open_api("GET", path, query={"voc_id": voc})
        items = j.get("data", {}).get(key, []) if isinstance(j, dict) else []
        print(f"── {label}（{len(items)} 条）")
        for it in items:
            if label == "释义":
                print(f"   [{it.get('status')}] {it.get('interpretation')!r}  tags={it.get('tags')}")
            elif label == "例句":
                print(f"   [{it.get('status')}] {it.get('phrase')!r}")
                print(f"        翻译={it.get('interpretation')!r} origin={it.get('origin')!r} tags={it.get('tags')}")
            else:
                print(f"   [{it.get('status')}] type={it.get('note_type')!r} note={it.get('note')!r}")
        print()


def cmd_whoami():
    t = load_tokens()
    print("凭证状态：")
    for k in ("open_token", "web_token"):
        v = t.get(k, {})
        tok = v.get(k) or v.get("open_token") or ""
        print(f"  {k:12} 有效期至 {v.get('expire', '?')}  ({tok[:16]}…)")
    try:
        print(f"\n配置目录：{CFG_DIR}")
        if os.path.exists(COF_FILE):
            cof = json.load(open(COF_FILE, encoding="utf-8"))
            print(f"账号：{cof.get('account')}")
    except Exception:
        pass


# ────────────────────────── CLI ──────────────────────────

def main():
    p = argparse.ArgumentParser(description="墨墨记单词 — 写入/查询释义、例句、助记")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="查看凭证状态")

    sp = sub.add_parser("vocab", help="查询词条拿 voc_id")
    sp.add_argument("word")

    sp = sub.add_parser("list", help="列出某词的全部内容")
    sp.add_argument("word")
    sp.add_argument("--type", default="all", choices=["all", "interp", "phrase", "note"])

    sp = sub.add_parser("interp-add", help="创建释义")
    sp.add_argument("--word", required=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--tags", nargs="*", default=["考研"])
    sp.add_argument("--public", action="store_true")

    sp = sub.add_parser("interp-del", help="删除释义")
    sp.add_argument("--id", required=True)

    sp = sub.add_parser("phrase-add", help="创建例句")
    sp.add_argument("--word", required=True)
    sp.add_argument("--phrase", required=True)
    sp.add_argument("--interp", required=True)
    sp.add_argument("--tags", nargs="*", default=["考研"])
    sp.add_argument("--origin", default="")
    sp.add_argument("--public", action="store_true")

    sp = sub.add_parser("phrase-del", help="删除例句")
    sp.add_argument("--id", required=True)

    sp = sub.add_parser("note-add", help="创建文本助记")
    sp.add_argument("--word", required=True)
    sp.add_argument("--type", default="其他", choices=NOTE_TYPES_TEXT)
    sp.add_argument("--text", required=True)
    sp.add_argument("--publish", action="store_true")

    sp = sub.add_parser("note-del", help="删除助记")
    sp.add_argument("--id", required=True)
    sp.add_argument("--note-type", required=True)
    sp.add_argument("--text", default="")

    sp = sub.add_parser("image-note", help="创建图片助记（图例）")
    sp.add_argument("--word", required=True)
    sp.add_argument("--image", required=True)
    sp.add_argument("--private-voc", default=None)

    sp = sub.add_parser("set-voc", help="登记私有 voc_id（24 位 hex）到缓存")
    sp.add_argument("--word", required=True)
    sp.add_argument("--voc", required=True)

    sp = sub.add_parser("voc-cache", help="查看已缓存的私有 voc_id")

    args = p.parse_args()

    if args.cmd == "whoami":
        cmd_whoami()
    elif args.cmd == "vocab":
        print(get_voc_id(args.word))
    elif args.cmd == "list":
        cmd_list(args.word, args.type)
    elif args.cmd == "interp-add":
        interp_add(args.word, args.text, args.tags, args.public)
    elif args.cmd == "interp-del":
        interp_del(args.id)
    elif args.cmd == "phrase-add":
        phrase_add(args.word, args.phrase, args.interp, args.tags, args.origin, args.public)
    elif args.cmd == "phrase-del":
        phrase_del(args.id)
    elif args.cmd == "note-add":
        note_add(args.word, args.type, args.text, args.publish)
    elif args.cmd == "note-del":
        note_del(args.id, args.note_type, args.text)
    elif args.cmd == "image-note":
        image_note(args.word, args.image, args.private_voc)
    elif args.cmd == "set-voc":
        put_priv_voc(args.word, args.voc.strip().lower())
    elif args.cmd == "voc-cache":
        c = load_priv_voc_cache()
        if not c:
            print("（空）尚未登记任何私有 voc_id。用 set-voc 添加。")
        else:
            print(f"已缓存 {len(c)} 个：")
            for w, h in sorted(c.items()):
                print(f"   {w:<24} {h}")


if __name__ == "__main__":
    main()
