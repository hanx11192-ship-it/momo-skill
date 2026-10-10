#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨墨开放平台 (open.maimemo.com) 短效 OpenAPI Token 自动获取
==========================================================
纯 HTTP 实现（无需浏览器），完整复刻官方 OAuth2/OIDC 授权码流程：

  1. GET  /open/api/v1/tokens/openapi            -> 302 accounts.maimemo.com/oidc/auth
  2. GET  /oidc/auth?client_id=...&response_type=code&state=... -> 303 /interaction/<uid>
  3. GET  /interaction/<uid>                     -> 登录页 HTML，解析表单 action + csrf
  4. POST /interaction/<uid>/login               -> 303 回 /oidc/auth/<uid>
  5. GET  /oidc/auth/<uid>                       -> 302 回 open.maimemo.com?code=xxx
  6. GET  回调页                                  -> 200，页面内含一次性 Access Token

与 App 私有协议 Token 的区分：
  - 本脚本产出的是「开放平台 OpenAPI Token」，24h 有效，用于 open.maimemo.com 的 REST API。
  - 输出文件 token.json 中固化为顶层键 "open_token"，值为一个 dict；
    后续 App 私有协议 token 建议使用其它顶层键（如 "app_token"），互不覆盖。

文件约定（均位于本脚本同目录）：
  cof.json    输入配置：{"email": "...", "password": "..."}
  token.json  输出结果：{"open_token": {"open_token": "...", ...}}

用法：
  python open_token.py                 # 读 cof.json，取 token，写入 token.json
  python open_token.py --verify        # 取到后调用 OpenAPI 验证
  python open_token.py --json          # 额外把结果打印为 JSON
  python open_token.py --debug         # 打印流程调试信息
  python open_token.py -u a@b.com -p pass   # 临时覆盖配置里的账号
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar

try:
    import requests
except ImportError:  # 无 requests 时自动降级到 urllib
    requests = None


# ==========================================================================
# 路径与常量
# ==========================================================================
BASE_DIR = os.environ.get("MAIMEMO_CONFIG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cfg"))
CONFIG_FILE = os.path.join(BASE_DIR, "cof.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "token.json")

OPEN_HOST = "https://open.maimemo.com"
TOKEN_ENTRY = OPEN_HOST + "/open/api/v1/tokens/openapi"
ACCOUNTS_HOST = "https://accounts.maimemo.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# token.json 中本脚本使用的顶层键
TOKEN_KEY = "open_token"

_MISSING = object()


class TokenError(RuntimeError):
    pass


class _CIHeaders(dict):
    """大小写不敏感的头字典（urllib 会把头键名小写化）。"""

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default

    def __getitem__(self, key):
        v = self.get(key, _MISSING)
        if v is _MISSING:
            raise KeyError(key)
        return v

    def __contains__(self, key):
        return any(k.lower() == key.lower() for k in self.keys())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止 urllib 自动跟随重定向，让 302 以 HTTPError 形式暴露 Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ==========================================================================
# 配置读取
# ==========================================================================
def load_config():
    """读取同目录 cof.json，返回 (account, password)。"""
    if not os.path.exists(CONFIG_FILE):
        raise TokenError(
            f"未找到配置文件: {CONFIG_FILE}\n"
            f'请创建，格式为: {{"account": "你的账号", "password": "你的密码"}}'
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise TokenError(f"cof.json 不是合法 JSON: {e}")

    account = cfg.get("account") or cfg.get("email") or cfg.get("user")
    password = cfg.get("password") or cfg.get("pass")
    if not account or not password:
        raise TokenError('cof.json 缺少 "account"(或 email) 或 "password" 字段')
    return account, password


# ==========================================================================
# 流程实现：requests 版
# ==========================================================================
class RequestsFlow:
    def __init__(self, user, password, timeout=30, debug=False):
        self.user = user
        self.password = password
        self.timeout = timeout
        self.debug = debug
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})

    def _log(self, *a):
        if self.debug:
            print("[debug]", *a, file=sys.stderr)

    def run(self):
        # 1. 入口 -> 授权跳转
        r = self.s.get(TOKEN_ENTRY, allow_redirects=False)
        if r.status_code not in (301, 302, 303, 307, 308):
            raise TokenError(f"入口未跳转: HTTP {r.status_code}")
        auth_url = urllib.parse.urljoin(TOKEN_ENTRY, r.headers["Location"])
        self._log("auth_url:", auth_url)

        # 2. OIDC 授权端点 -> interaction 页
        r = self.s.get(auth_url, allow_redirects=False)
        if r.status_code not in (301, 302, 303, 307, 308):
            raise TokenError(f"授权端点未跳转: HTTP {r.status_code}")
        interaction_url = urllib.parse.urljoin(ACCOUNTS_HOST, r.headers["Location"])
        self._log("interaction_url:", interaction_url)

        # 3. 登录页解析
        r = self.s.get(interaction_url)
        r.raise_for_status()
        login_action, csrf = _parse_login_form(r.text, interaction_url)
        self._log("login_action:", login_action)

        # 4. 提交账号密码
        r = self.s.post(
            login_action,
            data={"csrf": csrf, "identity": self.user, "password": self.password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": interaction_url,
                "Origin": ACCOUNTS_HOST,
            },
            allow_redirects=False,
        )
        if r.status_code not in (301, 302, 303, 307, 308):
            raise TokenError(f"登录失败: HTTP {r.status_code} {_extract_error(r.text)}")
        resume_url = urllib.parse.urljoin(ACCOUNTS_HOST, r.headers["Location"])
        self._log("resume_url:", resume_url)

        # 5. 拿到回跳地址
        r = self.s.get(resume_url, allow_redirects=False)
        callback = _extract_callback(r, resume_url)

        # 6. 用 code 换 token 展示页
        r = self.s.get(callback)
        r.raise_for_status()
        return _parse_token_page(r.text)


# ==========================================================================
# 流程实现：urllib 降级版
# ==========================================================================
class UrllibFlow:
    def __init__(self, user, password, timeout=30, debug=False):
        self.user = user
        self.password = password
        self.timeout = timeout
        self.debug = debug
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()),
            NoRedirect(),
        )

    def _log(self, *a):
        if self.debug:
            print("[debug]", *a, file=sys.stderr)

    def _req(self, url, data=None, headers=None, method=None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", UA)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.status, _CIHeaders(resp.headers), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, _CIHeaders(e.headers), e.read().decode("utf-8", "replace")

    def run(self):
        st, h, _ = self._req(TOKEN_ENTRY)
        if not h.get("Location"):
            raise TokenError(f"入口未跳转: HTTP {st}")
        auth_url = urllib.parse.urljoin(TOKEN_ENTRY, h["Location"])

        st, h, _ = self._req(auth_url)
        if not h.get("Location"):
            raise TokenError(f"授权端点未跳转: HTTP {st}")
        interaction_url = urllib.parse.urljoin(ACCOUNTS_HOST, h["Location"])

        st, h, page = self._req(interaction_url)
        login_action, csrf = _parse_login_form(page, interaction_url)

        body = urllib.parse.urlencode(
            {"csrf": csrf, "identity": self.user, "password": self.password}
        ).encode()
        st, h, page = self._req(
            login_action,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": interaction_url,
                "Origin": ACCOUNTS_HOST,
            },
            method="POST",
        )
        if not h.get("Location"):
            raise TokenError(f"登录失败: HTTP {st} {_extract_error(page)}")
        resume_url = urllib.parse.urljoin(ACCOUNTS_HOST, h["Location"])

        st, h, page = self._req(resume_url)
        callback = _extract_callback_urllib(h, page, resume_url)

        st, h, page = self._req(callback)
        return _parse_token_page(page)


# ==========================================================================
# 解析辅助
# ==========================================================================
def _parse_login_form(page, interaction_url):
    m = (re.search(r'<form[^>]*id="form-password"[^>]*action="([^"]+)"', page)
         or re.search(r'<form[^>]*action="([^"]*login)"', page))
    if not m:
        raise TokenError("登录页未找到密码登录表单")
    login_action = urllib.parse.urljoin(interaction_url, m.group(1))

    m = re.search(r'name="csrf"\s+value="([^"]+)"', page)
    if not m:
        raise TokenError("登录页未找到 csrf token")
    return login_action, m.group(1)


def _extract_error(html):
    m = re.search(r'class="error-text"[^>]*>(.*?)</div>', html, re.S)
    if m:
        return "-> " + re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return ""


def _extract_callback(resp, resume_url):
    if resp.status_code in (301, 302, 303, 307, 308):
        return urllib.parse.urljoin(resume_url, resp.headers["Location"])
    m = re.search(r'https://open\.maimemo\.com/[^"\'\s<>]+code=[^"\'\s<>]+', resp.text)
    if not m:
        raise TokenError(f"未获得回跳地址: HTTP {resp.status_code}")
    return m.group(0)


def _extract_callback_urllib(headers, page, resume_url):
    if headers.get("Location"):
        return urllib.parse.urljoin(resume_url, headers["Location"])
    m = re.search(r'https://open\.maimemo\.com/[^"\'\s<>]+code=[^"\'\s<>]+', page)
    if not m:
        raise TokenError("未获得回跳地址")
    return m.group(0)


def _to_local_str(raw):
    """ISO8601(UTC, 带 Z) 或 'YYYY/MM/DD HH:MM:SS' -> 本地时间字符串。"""
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        return raw
    except Exception:
        return raw


def _parse_token_page(html):
    if "获取 Token 失败" in html or "state 校验失败" in html:
        raise TokenError("授权失败(state 校验失败)，请重试")
    cands = re.findall(r"[A-Za-z0-9_\-]{40,}", html)
    if not cands:
        raise TokenError("页面中未找到 Token")
    token = max(cands, key=len)

    raw = None
    m = re.search(r'id="expiryTime"[^>]*>([^<]+)<', html)
    if m:
        raw = m.group(1).strip()
    if not raw:
        m = re.search(r"([0-9]{4}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})", html)
        raw = m.group(1) if m else None
    return {"token": token, "expire_raw": raw}


# ==========================================================================
# 输出
# ==========================================================================
def build_record(result, account):
    """组装写入 token.json 的 open_token 记录。"""
    raw = result.get("expire_raw")
    expire_iso = None      # ISO 8601 本地时间
    expire_ts = None       # Unix 时间戳(秒)
    if raw:
        try:
            if raw.endswith("Z"):
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
            else:
                dt = datetime.strptime(raw, "%Y/%m/%d %H:%M:%S").astimezone()
            expire_iso = dt.isoformat(timespec="seconds")
            expire_ts = int(dt.timestamp())
        except Exception:
            expire_iso = _to_local_str(raw)

    return {
        "open_token": result["token"],
        "expire": expire_iso,
        "expire_ts": expire_ts,
        "account": account,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fetched_ts": int(time.time()),
    }


def save_output(record):
    """把 open_token 合并写入 token.json（保留其它顶层键，如未来的 app_token）。"""
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


def verify_token(token, timeout=20):
    """调用 OpenAPI 验证 token 有效性。"""
    url = OPEN_HOST + "/open/api/v1/notepads?limit=1"
    if requests:
        r = requests.get(url, headers={"Authorization": "Bearer " + token}, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# ==========================================================================
# 入口
# ==========================================================================
def main():
    ap = argparse.ArgumentParser(description="墨墨开放平台 短效 OpenAPI Token 获取")
    ap.add_argument("-u", "--user", help="临时覆盖 cof.json 中的邮箱")
    ap.add_argument("-p", "--password", help="临时覆盖 cof.json 中的密码")
    ap.add_argument("--json", action="store_true", help="额外打印 JSON 结果")
    ap.add_argument("--verify", action="store_true", help="取到后调用 OpenAPI 验证")
    ap.add_argument("--debug", action="store_true", help="打印流程调试信息")
    ap.add_argument("--no-save", action="store_true", help="不写入 token.json")
    args = ap.parse_args()

    try:
        cfg_email, cfg_pass = load_config()
    except TokenError as e:
        print(f"[x] 配置错误: {e}", file=sys.stderr)
        return 1

    user = args.user or cfg_email
    password = args.password or cfg_pass

    flow = (RequestsFlow(user, password, debug=args.debug) if requests
            else UrllibFlow(user, password, debug=args.debug))

    try:
        result = flow.run()
    except TokenError as e:
        print(f"[x] 获取失败: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[x] 异常: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    record = build_record(result, user)
    out = {"success": True, **record}

    if args.verify:
        code, body = verify_token(record["open_token"])
        out["verify_status"] = code
        out["verify_ok"] = bool(isinstance(body, dict) and body.get("success"))

    saved = None
    if not args.no_save:
        saved = save_output(record)
        out["saved_to"] = saved

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("  墨墨开放平台 OpenAPI Token")
        print("=" * 62)
        print(f"  账号      : {user}")
        print(f"  Token     : {record['open_token']}")
        print(f"  过期时间  : {record['expire'] or '(页面未显示)'}")
        print(f"  过期戳    : {record['expire_ts']}")
        if args.verify:
            print(f"  验证      : HTTP {out.get('verify_status')} "
                  f"{'OK 可用' if out.get('verify_ok') else 'FAIL 无效'}")
        if saved:
            print(f"  已写入    : {saved}")
        print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
