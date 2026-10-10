#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨墨 web 端 (www.maimemo.com) userToken 获取脚本
==============================================
登录 www.maimemo.com 后，从 Set-Cookie 中提取 userToken 并写入 token.json。

背景：web 端 userToken 与 App/开放平台 token 不同，但可用于 App 私有协议
（上传/删除/添加图片助记等）的接口调用。其有效期约 1 年（Max-Age=31104000）。

登录接口（实测，纯表单，无签名/无验证码）：
    POST https://www.maimemo.com/auth/login
    Content-Type: application/x-www-form-urlencoded; charset=UTF-8
    X-Requested-With: XMLHttpRequest
    body: email=<账号>&password=<密码>
    -> 200 {"valid":1}
    -> Set-Cookie: PHPSESSID=...; userToken=<TOKEN>; (domain=www.maimemo.com)

文件约定（均位于本脚本同目录）：
  cof.json    输入配置：{"account": "...", "password": "..."}（兼容 email/user + pass）
  token.json  输出结果：顶层键 "web_token" 记录本次结果，与 "open_token" 等共存不冲突

用法：
    python web_token.py                 # 读 cof.json，取 userToken，写入 token.json
    python web_token.py --json          # 额外打印 JSON
    python web_token.py --debug         # 打印调试信息
    python web_token.py --no-save       # 不写入 token.json
    python web_token.py -a 账号 -p 密码  # 临时覆盖配置
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar

try:
    import requests
except ImportError:
    requests = None

# ==========================================================================
# 路径与常量
# ==========================================================================
BASE_DIR = os.environ.get("MAIMEMO_CONFIG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cfg"))
CONFIG_FILE = os.path.join(BASE_DIR, "cof.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "token.json")

LOGIN_URL = "https://www.maimemo.com/auth/login"
REFERER = "https://www.maimemo.com/home/login"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

TOKEN_KEY = "web_token"
COOKIE_NAME = "userToken"


class WebTokenError(RuntimeError):
    pass


# ==========================================================================
# 配置
# ==========================================================================
def load_config():
    """读取同目录 cof.json，返回 (account, password)。"""
    if not os.path.exists(CONFIG_FILE):
        raise WebTokenError(
            f"未找到配置文件: {CONFIG_FILE}\n"
            f'请创建，格式为: {{"account": "你的账号", "password": "你的密码"}}'
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise WebTokenError(f"cof.json 不是合法 JSON: {e}")

    account = cfg.get("account") or cfg.get("email") or cfg.get("user")
    password = cfg.get("password") or cfg.get("pass")
    if not account or not password:
        raise WebTokenError('cof.json 缺少 "account"(或 email) 或 "password" 字段')
    return account, password


# ==========================================================================
# 登录实现
# ==========================================================================
def fetch_webtoken_requests(account, password, timeout=30, debug=False):
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.maimemo.com",
        "Referer": REFERER,
    })
    r = s.post(
        LOGIN_URL,
        data={"email": account, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=timeout,
    )
    _check_body(r.text)
    token = s.cookies.get(COOKIE_NAME)
    if not token:
        # 有些实现 cookie 挂在 .maimemo.com 域
        for c in s.cookies:
            if c.name == COOKIE_NAME:
                token = c.value
                break
    if not token:
        raise WebTokenError("响应中未找到 userToken cookie")
    return token, dict(r.headers)


def fetch_webtoken_urllib(account, password, timeout=30, debug=False):
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    body = urllib.parse.urlencode({"email": account, "password": password}).encode()
    req = urllib.request.Request(LOGIN_URL, data=body, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("X-Requested-With", "XMLHttpRequest")
    req.add_header("Origin", "https://www.maimemo.com")
    req.add_header("Referer", REFERER)
    try:
        with opener.open(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        raise WebTokenError(f"登录请求失败: HTTP {e.code}")

    _check_body(text)
    token = None
    for c in cj:
        if c.name == COOKIE_NAME:
            token = c.value
            break
    if not token:
        raise WebTokenError("响应中未找到 userToken cookie")
    return token, headers


def _check_body(text):
    """登录响应体校验：成功为 {"valid":1}。"""
    t = text.strip()
    try:
        j = json.loads(t)
    except Exception:
        raise WebTokenError(f"登录响应非 JSON: {t[:200]}")
    if not (isinstance(j, dict) and j.get("valid")):
        raise WebTokenError(f"登录失败，响应: {t[:200]}")


# ==========================================================================
# 输出
# ==========================================================================
def build_record(token, account):
    now = datetime.now().astimezone()
    # web userToken 有效期约 1 年 (Max-Age=31104000s)
    from datetime import timedelta
    expire_dt = now + timedelta(seconds=31104000)
    return {
        "web_token": token,
        "expire": expire_dt.isoformat(timespec="seconds"),
        "expire_ts": int(expire_dt.timestamp()),
        "account": account,
        "fetched_at": now.isoformat(timespec="seconds"),
        "fetched_ts": int(now.timestamp()),
        "note": "www.maimemo.com userToken，约1年有效，可用于App私有协议接口",
    }


def save_output(record):
    """增量合并写入 token.json，保留其它顶层键（open_token / app_token 等）。"""
    data = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    data[TOKEN_KEY] = record
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return OUTPUT_FILE


# ==========================================================================
# 入口
# ==========================================================================
def main():
    ap = argparse.ArgumentParser(description="墨墨 web 端 userToken 获取")
    ap.add_argument("-a", "--account", help="临时覆盖 cof.json 中的账号")
    ap.add_argument("-p", "--password", help="临时覆盖 cof.json 中的密码")
    ap.add_argument("--json", action="store_true", help="额外打印 JSON 结果")
    ap.add_argument("--debug", action="store_true", help="打印调试信息")
    ap.add_argument("--no-save", action="store_true", help="不写入 token.json")
    args = ap.parse_args()

    try:
        cfg_acc, cfg_pw = load_config()
    except WebTokenError as e:
        print(f"[x] 配置错误: {e}", file=sys.stderr)
        return 1

    account = args.account or cfg_acc
    password = args.password or cfg_pw

    try:
        if requests:
            token, headers = fetch_webtoken_requests(account, password, debug=args.debug)
        else:
            token, headers = fetch_webtoken_urllib(account, password, debug=args.debug)
    except WebTokenError as e:
        print(f"[x] 获取失败: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[x] 异常: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    record = build_record(token, account)
    out = {"success": True, **record}

    saved = None
    if not args.no_save:
        saved = save_output(record)
        out["saved_to"] = saved

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("  墨墨 web 端 userToken")
        print("=" * 62)
        print(f"  账号      : {account}")
        print(f"  web_token : {record['web_token']}")
        print(f"  过期时间  : {record['expire']}")
        print(f"  过期戳    : {record['expire_ts']}")
        if saved:
            print(f"  已写入    : {saved}")
        print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
