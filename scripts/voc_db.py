# -*- coding: utf-8 -*-
"""
voc_db.py —— 查询墨墨私有 voc_id（24 位 hex，Mongo ObjectId）。

两级来源，自动降级：
  1. references/voc_index.tsv —— 内置离线索引（128,683 词，覆盖
     App 本地库 VOC_TB 全部唯一拼写），查询 0.2s，无需手机。★ 默认路径。
  2. 本地缓存库 .cache/momo.v425.db —— 之前经 adb 拉取过的完整库
     （App 词库更新后索引查不到的生僻词走这里）。
  3. adb(root) 实时拉取 —— 手机 USB 连接且已 root 时，可 `--pull` 刷新。

用法：
    python voc_db.py button sleep        # 查词（自动走 1→2）
    python voc_db.py --pull ubiquitous   # 强制从手机重新拉库后查
"""
import argparse
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
INDEX = os.path.join(SKILL, "references", "voc_index.tsv")
CACHE = os.path.join(HERE, ".cache")
DB_LOCAL = os.path.join(CACHE, "momo.v425.db")

PKG = "com.maimemo.android.momo"
REMOTE_DB = f"/data/data/{PKG}/databases/momo.v425.db"
TMP_DB = "/data/local/tmp/_mm_pull.db"
ADB = os.environ.get("ADB", shutil.which("adb") or "adb")

_index = None


def _load_index():
    """加载 TSV 索引（word TAB id，# 开头为注释行）。首次调用后缓存。"""
    global _index
    if _index is None:
        idx = {}
        with open(INDEX, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or "\t" not in line:
                    continue
                w, _, v = line.rstrip("\n").partition("\t")
                if w and v:
                    idx[w] = [v]
        _index = idx
    return _index


def _adb(*args, timeout=180):
    return subprocess.run([ADB] + list(args), capture_output=True, text=True,
                          timeout=timeout)


def pull_db(force=False):
    """通过 adb(需 root) 拉取数据库到本地缓存。返回本地路径。"""
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(DB_LOCAL) and not force:
        return DB_LOCAL
    cp = _adb("shell", "su", "-c",
              f"cp '{REMOTE_DB}' {TMP_DB} && chmod 666 {TMP_DB}")
    if cp.returncode != 0 and "No such file" in (cp.stderr + cp.stdout):
        raise RuntimeError(f"adb/su 失败或文件不存在：{cp.stderr.strip()}")
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run([ADB, "pull", TMP_DB, DB_LOCAL],
                       capture_output=True, text=True, env=env, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"adb pull 失败：{r.stderr.strip()}")
    _adb("shell", "rm", "-f", TMP_DB)
    return DB_LOCAL


def _lookup_db(words, db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = {}
    try:
        for w in words:
            row = conn.execute(
                "SELECT id FROM VOC_TB WHERE spelling = ? COLLATE NOCASE LIMIT 1",
                (w,),
            ).fetchone()
            if row and row[0]:
                out[w] = row[0]
    finally:
        conn.close()
    return out


def lookup(words, db_path=None, allow_pull=True):
    """words: list[str] -> {word: voc_id}（查不到的词不在返回 dict 中）。

    顺序：内置索引 → 本地缓存库 → （可选）adb 实时拉库。
    """
    words = list(dict.fromkeys(w for w in words if w))
    out = {}
    rest = []

    # 1) 内置离线索引
    idx = _load_index()
    for w in words:
        v = idx.get(w.lower())
        if v:
            out[w] = v[0]
        else:
            rest.append(w)

    # 2) 本地缓存库（adb 拉取过的最新 App 词库）
    if rest and (db_path or os.path.exists(DB_LOCAL)):
        try:
            got = _lookup_db(rest, db_path or DB_LOCAL)
            out.update(got)
            rest = [w for w in rest if w not in got]
        except Exception:
            pass

    # 3) adb 实时拉库
    if rest and allow_pull:
        try:
            db = pull_db()
            got = _lookup_db(rest, db)
            out.update(got)
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser(description="查询墨墨私有 voc_id")
    ap.add_argument("--pull", action="store_true",
                    help="强制从手机重新拉取数据库（需 USB + root）")
    ap.add_argument("--db", default=None, help="指定本地数据库路径")
    ap.add_argument("words", nargs="*", help="要查询的单词")
    a = ap.parse_args()

    if a.pull:
        p = pull_db(force=True)
        print(f"[+] 已从手机拉取 -> {p}", file=sys.stderr)
    if not a.words:
        n = len(_load_index())
        src = "内置索引" if os.path.exists(INDEX) else "(无索引)"
        print(f"[i] {src} {n} 词；本地库缓存: {DB_LOCAL if os.path.exists(DB_LOCAL) else '无'}")
        return

    res = lookup(a.words, a.db, allow_pull=not a.db)
    for w in a.words:
        vid = res.get(w)
        print(f"{w}\t{vid if vid else '<未收录>'}")


if __name__ == "__main__":
    main()
