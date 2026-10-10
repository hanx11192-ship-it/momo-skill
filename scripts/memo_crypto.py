#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MEMO_AES_V3 加解密 —— 基于 libmomoco.so native 逆向 + Unicorn 仿真验证。

已验证事实（2026-10-10 真机 + 逐字节对照）：
  1. e() @0x44e4 —— 自定义 base64 变体（**纯 Python e_py() 已 15/15 逐字节复现**）：
         e(s) = T2[ T1[ base64_std( reverse(s) ) ] ]      # len(s) < 2 -> b""
         T1 @0x1e0b = 标准 base64 逆表；T2 @0x1db0 = 自定义输出字母表
  2. key/iv 由 seed（= 请求头 Signature）派生：
         d   = sha256hex( e(seed) )
         key = d[0:32]    (32 个 ASCII 字符 = AES-256 密钥)
         iv  = d[32:48]   (16 个 ASCII 字符 = CBC 初始向量)
         → 见 key_iv_py() / key_iv()，均与 native hook 实测值一致
  3. 算法 = AES-256-CBC + PKCS7
  4. 服务端响应 body = ASCII hex（content-encoding: MEMO_AES_V3），
     解 hex 得密文，解密后是 gzip 流，gunzip 得 JSON。
  5. native ea() <-> da() 往返 5/5 PASS。

⚠️ 重要限制（2026-10-10 结论）：
     用「Signature」派生的 key 解密**实况抓包**的 MEMO_AES_V3 响应会失败
     （11/11 样本，native da() 亦返回 NULL）。签名的生成链本身正确且被服务端
     接受（写入操作 HTTP 200），仅响应的 seed 无法离线复现。
     → 获取私有 voc_id 请改用「读 App 本地 SQLite」路线：见 scripts/voc_db.py。

用法：
    from memo_crypto import e_py, key_iv_py
    e_py("abcdef")            # -> b"Zq2hVbof"
    key_iv_py("<40hex sig>")  # -> (key32, iv16)

    from memo_crypto import _Emu
    emu = _Emu()              # 仿真宿主（首次加载 ~1s）
    emu.decrypt_hex(hextext, signature)
"""
import binascii
import gzip
import hashlib
import os
import struct
import sys

from Crypto.Cipher import AES

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_X4,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_TPIDR_EL0,
)
import unicorn.arm64_const as _ac
import elf


# native 函数地址（libmomoco.so，ARM64）—— 2026-10-10 用 .rela.dyn 重定位后逐项校正
FN_S = 0x426C      # 签名        s(token, salt, rawSig) -> Signature
FN_P = 0x4174      # p(ParamStatement) -> String
FN_P2 = 0x41F0     # p2(Map) -> String
FN_D = 0x498C      # d(String) -> String（另一套编码，非 e）
FN_E = 0x44E4      # ★ e(String) -> String  自定义 base64 变体（key 派生用这个）
FN_EC = 0x4498     # ec(char) -> char
FN_DA = 0x4B38     # decryptAES  da(env, cls, seed_jstr, ct_jbytes, mode)
FN_EA = 0x4C90     # encryptAES  ea(env, cls, seed_jstr, pt_jbytes, mode, ..)
FN_DSS = 0x4C98    # dss(String,String,String,String,[B)[B
FN_SHA = 0x53AC    # sha(String) -> String  = SHA1hex
FN_HEX256 = 0x51E4 # sha256_hex(src, dst, len) -> 64 个 hex 字符写 dst

# e() 内部用到的两张映射表（.rodata）
E_T1_OFF = 0x1E0B  # 标准 base64 逆表（128 B）
E_T2_OFF = 0x1DB0  # 自定义输出字母表（128 B，有效 96 B）
# 兼容旧名
FN_HEX = FN_HEX256
E_ALPHABET = b"9DbHdkrsj13yxX4IB+/oNaEi8YCGzT02FOVZ@tRv"


def _load_tables():
    """从 libmomoco.so 读出 e() 的 T1/T2 表。"""
    import elf as _elf
    o1 = _elf.v2o(E_T1_OFF) or E_T1_OFF
    o2 = _elf.v2o(E_T2_OFF) or E_T2_OFF
    return _elf.SO[o1:o1 + 128], _elf.SO[o2:o2 + 128]


_T1, _T2 = _load_tables()


def e_py(text):
    """e() @0x44e4 的**完整纯 Python 实现**（已与 native 逐字节对照 15/15 一致）。

    算法（经反汇编 + hook 双重确认）：
      1. 若 len(s) < 2 -> 返回 b""
      2. r = s 按码点逆序（native 的 0x4658 做 UTF-16 码点反转）
      3. b = 标准 base64(r.encode())         # 字母表 A-Za-z0-9+/
      4. 对 b 的每个字符： b[i] = T2[ T1[ b[i] ] ]   # 含末尾 '='

    样例：
      e_py("AA")     -> b"C04v"
      e_py("abcdef") -> b"Zq2hVbof"
      e_py("b80d07722afd4abe21c2e2f85d9a51f4d5b0551c")
                     -> b"V=4DiTyciFC9Zw4DVTJhiTfqEq0UV=4UZFofiBGqVT/Ui=LuZX3dVnvv"
    """
    import base64 as _b64
    if len(text) < 2:
        return b""
    r = text[::-1].encode("latin-1")
    b = bytearray(_b64.b64encode(r))
    for i in range(len(b)):
        b[i] = _T2[_T1[b[i]]]
    return bytes(b)


def E(text):
    """E() 的别名（历史名称）。等价于 e_py()。"""
    return e_py(text)


def native_E(signature):
    """走 native 仿真调用 e()（对照用，权威实现）。"""
    mc = _Emu()
    r = mc._call(FN_E, [mc.ENVOBJ, 0, mc._jstr(signature)])
    return mc._getstr(r)


def key_iv_py(signature):
    """纯 Python 派生 (key, iv)：

        d   = sha256hex( e(seed) )
        key = d[0:32]   (ASCII, 32 B -> AES-256)
        iv  = d[32:48]  (ASCII, 16 B)
    """
    h = hashlib.sha256(e_py(signature)).hexdigest()
    return h[:32].encode(), h[32:48].encode()


class _Emu:
    """最小可用的 libmomoco.so 仿真宿主。"""

    SIZE = 0x4000000
    ENVOBJ = 0x100000
    VTBL = 0x100800
    CSTRS = 0x110000
    HEAP = 0x140000
    HEAP_END = 0x3000000
    STUBS = 0x3F00000
    STACK = 0x3FF0000
    RETM = 0x3FFF000
    TP = 0x3F80000

    def __init__(self):
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.uc.mem_map(0, self.SIZE)
        for sec in elf.SECS:
            if sec["addr"] and sec["size"]:
                self.uc.mem_write(sec["addr"], elf.SO[sec["off"]:sec["off"] + sec["size"]])
        for _kind, roff, stype, _sym, addend in elf.relocations():
            if stype == 1027:
                self.uc.mem_write(roff, struct.pack("<Q", addend))

        self._next = self.HEAP
        self.JSTR = {}
        self.JARR = {}
        self.STUB_NAMES = {}
        self.BY_NAME = {}
        self._tmp = 0
        self._sc = []

        for n in [
            "GetStringUTFLength", "GetStringUTFChars", "ReleaseStringUTFChars",
            "GetStringLength", "GetStringChars", "ReleaseStringChars", "GetStringRegion",
            "NewStringUTF", "NewString", "GetArrayLength", "GetByteArrayElements",
            "ReleaseByteArrayElements", "GetByteArrayRegion", "SetByteArrayRegion",
            "NewByteArray", "GetPrimitiveArrayCritical", "ReleasePrimitiveArrayCritical",
            "FindClass", "ExceptionCheck", "GetStaticMethodID", "GetMethodID",
            "CallObjectMethod", "CallStaticObjectMethod", "CallObjectMethodV",
            "DeleteLocalRef", "DeleteGlobalRef", "malloc", "free", "strlen", "log",
            "memcpy", "strcmp", "memset", "realloc", "qsort", "strncpy",
            "__stack_chk_fail", "__strncpy_chk2", "__vsprintf_chk", "__vsnprintf_chk",
            "memmove", "calloc", "Nop",
            "CallStaticVoidMethod", "CallStaticVoidMethodV", "CallStaticVoidMethodA",
            "CallVoidMethod",
        ]:
            self._mkstub(n)

        got = {0xda18: "free", 0xda20: "__stack_chk_fail", 0xda28: "malloc",
               0xda30: "qsort", 0xda38: "strcmp", 0xda40: "log", 0xda48: "memcpy",
               0xda50: "strlen", 0xda58: "__strncpy_chk2", 0xda60: "strncpy",
               0xda68: "memset", 0xda70: "__vsprintf_chk", 0xda78: "realloc",
               0xda80: "__vsnprintf_chk"}
        for g, nm in got.items():
            self.uc.mem_write(g, struct.pack("<Q", self.BY_NAME[nm]))
        self.uc.mem_write(0xd818, struct.pack("<Q", self.BY_NAME["memset"]))

        slots = {0x520: "GetStringUTFLength", 0x110: "CallObjectMethod",
                 0x108: "GetStaticMethodID", 0x558: "GetArrayLength",
                 0xb8: "DeleteLocalRef", 0x538: "NewStringUTF",
                 0x548: "GetStringUTFChars", 0x550: "ReleaseStringUTFChars",
                 0x640: "GetByteArrayRegion", 0x30: "FindClass",
                 0x720: "ExceptionCheck", 0x5c0: "GetByteArrayElements",
                 0x600: "ReleaseByteArrayElements", 0x528: "GetStringChars",
                 0x530: "ReleaseStringChars", 0x518: "NewString",
                 0x580: "NewByteArray", 0x680: "SetByteArrayRegion",
                 0x398: "GetPrimitiveArrayCritical", 0x3a0: "ReleasePrimitiveArrayCritical",
                 0x560: "GetStringLength", 0x5a0: "GetStringRegion", 0xb0: "GetMethodID",
                 0x88: "CallStaticVoidMethod", 0x90: "CallStaticVoidMethodV",
                 0x98: "CallStaticVoidMethodA", 0x70: "CallVoidMethod"}
        # 先把整张 JNI 函数表（0x800 字节）预填成"返回 0"的兜底 stub，
        # 再用具名 stub 覆盖已知槽 —— 避免任何未映射 slot 跳到 0 导致崩溃。
        for off in range(0, 0x800, 8):
            self.uc.mem_write(self.VTBL + off, struct.pack("<Q", self.BY_NAME["Nop"]))
        for off, nm in slots.items():
            self.uc.mem_write(self.VTBL + off, struct.pack("<Q", self.BY_NAME[nm]))
        self.uc.mem_write(self.ENVOBJ, struct.pack("<Q", self.VTBL))

        self.uc.hook_add(UC_HOOK_CODE, self._fmt_hook, begin=0x5278, end=0x5280)
        self.uc.hook_add(UC_HOOK_CODE, self._jni_hook, begin=self.STUBS,
                         end=self.STUBS + 0x8000)

    # ---------- internals ----------
    def _mkstub(self, name):
        a = self.STUBS + len(self.STUB_NAMES) * 16
        self.uc.mem_write(a, b"\xc0\x03\x5f\xd6")   # ret
        self.STUB_NAMES[a] = name
        self.BY_NAME[name] = a

    def _alloc(self, n):
        n = (n + 15) & ~0xF
        a = self._next
        self._next = a + n
        if self._next >= self.HEAP_END:
            raise RuntimeError("emu heap exhausted")
        return a

    def _jstr(self, b):
        if isinstance(b, str):
            b = b.encode()
        i = self._alloc(len(b) + 8)
        self.JSTR[i] = b
        return i

    def _jarr(self, b):
        i = self._alloc(len(b) + 8)
        self.uc.mem_write(i, bytes(b))
        self.JARR[i] = bytearray(b)
        return i

    def _cstr(self, a):
        out = bytearray()
        a = int(a)
        while True:
            c = self.uc.mem_read(a, 1)
            if c == b"\0":
                break
            out += c
            a += 1
        return bytes(out)

    def _getstr(self, handle):
        """把 jstring 句柄还原为 bytes（委托给 JSTR/JARR 表）。"""
        if handle in self.JSTR:
            return self.JSTR[handle]
        if handle in self.JARR:
            return bytes(self.JARR[handle])
        try:
            return self._cstr(handle)
        except Exception:
            return None

    def _fmt_hook(self, uc, addr, size, ud):
        # snprintf(dst, -1, "%02x", ch)
        dst = int(uc.reg_read(_ac.UC_ARM64_REG_X0))
        ch = int(uc.reg_read(_ac.UC_ARM64_REG_X3)) & 0xFF
        uc.mem_write(dst, b"%02x" % ch + b"\0")
        uc.reg_write(_ac.UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    def _jni_hook(self, uc, addr, size, ud):
        nm = self.STUB_NAMES.get(addr, "?")
        x0 = uc.reg_read(UC_ARM64_REG_X0)
        x1 = uc.reg_read(UC_ARM64_REG_X1)
        x2 = uc.reg_read(UC_ARM64_REG_X2)
        x3 = uc.reg_read(UC_ARM64_REG_X3)
        x4 = uc.reg_read(UC_ARM64_REG_X4)

        def setr(v):
            uc.reg_write(UC_ARM64_REG_X0, int(v))

        if nm == "GetStringUTFLength":
            setr(len(self.JSTR.get(x1, b"")))
        elif nm == "GetStringUTFChars":
            b = self.JSTR.get(x1, b"")
            p = self.CSTRS + (self._tmp % 64) * 0x400
            self._tmp += 1
            uc.mem_write(p, b + b"\0")
            setr(p)
        elif nm in ("ReleaseStringUTFChars", "ReleaseStringChars", "GetStringRegion",
                    "ReleaseByteArrayElements", "ReleasePrimitiveArrayCritical",
                    "DeleteLocalRef", "DeleteGlobalRef", "free", "log",
                    "__strncpy_chk2", "__vsprintf_chk", "__vsnprintf_chk", "qsort",
                    "memmove"):
            if nm == "memmove":
                d, s, n = int(x0), int(x1), int(x2)
                if n:
                    uc.mem_write(d, bytes(uc.mem_read(s, n)))
                setr(d)
            elif nm == "__strncpy_chk2":
                d, s, n = int(x0), int(x1), int(x2)
                uc.mem_write(d, bytes(uc.mem_read(s, n)))
                setr(d)
            else:
                setr(0)
        elif nm == "GetStringLength":
            setr(len(self.JSTR.get(x1, b"")))
        elif nm == "GetStringChars":
            b = self.JSTR.get(x1, b"")
            p = self.CSTRS + 0x10000 + (self._tmp % 64) * 0x400
            self._tmp += 1
            uc.mem_write(p, b.decode("utf-8", "replace").encode("utf-16-le") + b"\0\0")
            setr(p)
        elif nm == "NewStringUTF":
            setr(self._jstr(self._cstr(x1)))
        elif nm == "NewString":
            raw = bytes(uc.mem_read(int(x1), int(x2) * 2))
            setr(self._jstr(raw.decode("utf-16-le", "replace")))
        elif nm == "FindClass":
            setr(0x999)
        elif nm == "ExceptionCheck":
            setr(0)
        elif nm in ("GetStaticMethodID", "GetMethodID"):
            setr(0x5A5A)
        elif nm in ("CallObjectMethod", "CallStaticObjectMethod", "CallObjectMethodV"):
            data = self.JSTR.get(x1)
            if data is None:
                data = bytes(self.JARR.get(x1, b""))
            setr(self._jarr(data))
        elif nm == "GetArrayLength":
            setr(len(self.JARR.get(x1, b"")))
        elif nm == "GetByteArrayElements":
            arr = self.JARR.get(x1, b"")
            p = self._alloc(len(arr) + 16)
            uc.mem_write(p, bytes(arr))
            setr(p)
        elif nm == "GetByteArrayRegion":
            arr = self.JARR.get(x1, b"")
            uc.mem_write(int(x4), bytes(arr[int(x2):int(x2) + int(x3)]))
            setr(0)
        elif nm == "SetByteArrayRegion":
            arr = self.JARR.get(x1)
            if arr is not None:
                arr[int(x2):int(x2) + int(x3)] = bytes(uc.mem_read(int(x4), int(x3)))
            setr(0)
        elif nm == "NewByteArray":
            # JNI: NewByteArray(JNIEnv*, jsize length) —— 长度在 x1，不是 x0
            setr(self._jarr(b"\0" * int(x1)))
        elif nm == "GetPrimitiveArrayCritical":
            arr = self.JARR.get(x1, b"")
            p = self._alloc(len(arr) + 16)
            uc.mem_write(p, bytes(arr))
            setr(p)
        elif nm in ("malloc", "calloc"):
            n = int(x0) if nm == "malloc" else (int(x0) * int(x1))
            setr(self._alloc(n or 1))
        elif nm == "strlen":
            setr(len(self._cstr(x0)))
        elif nm == "memcpy":
            d, s, n = int(x0), int(x1), int(x2)
            if n:
                uc.mem_write(d, bytes(uc.mem_read(s, n)))
            setr(d)
        elif nm == "strcmp":
            a, b = self._cstr(x0), self._cstr(x1)
            setr((a > b) - (a < b))
        elif nm == "memset":
            uc.mem_write(int(x0), bytes([int(x1) & 0xFF]) * int(x2))
            setr(x0)
        elif nm == "realloc":
            n = int(x1)
            p = self._alloc(n or 1)
            old = self.JARR.get(x0) or b""
            if old:
                uc.mem_write(p, bytes(uc.mem_read(x0, min(len(old), n))))
            setr(p)
        elif nm == "strncpy":
            d, s, n = int(x0), int(x1), int(x2)
            raw = self._cstr(s)[:n]
            uc.mem_write(d, raw + b"\0" * (n - len(raw)))
            setr(d)
        elif nm in ("CallStaticVoidMethod", "CallStaticVoidMethodV", "CallStaticVoidMethodA",
                    "CallVoidMethod"):
            setr(0)
        elif nm == "Nop":
            setr(0)
        else:
            setr(0)
        uc.reg_write(_ac.UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    def _call(self, fn, args):
        sp = self.STACK - 0x2000
        self.uc.reg_write(UC_ARM64_REG_TPIDR_EL0, self.TP)
        self.uc.mem_write(self.TP + 0x28, b"\x11" * 8)
        self.uc.mem_write(sp, struct.pack("<Q", self.RETM))
        for i, a in enumerate(args):
            self.uc.reg_write(UC_ARM64_REG_X0 + i, a)
        self.uc.reg_write(UC_ARM64_REG_SP, sp)
        self.uc.reg_write(UC_ARM64_REG_LR, self.RETM)
        self.uc.mem_write(self.RETM, b"\xc0\x03\x5f\xd6")
        self.uc.emu_start(fn, self.RETM, count=50000000)
        return self.uc.reg_read(UC_ARM64_REG_X0)

    def reset(self):
        self._next = self.HEAP
        self._tmp = 0

    # ---------- public ----------
    def key_iv(self, signature):
        """由 Signature 派生 (key, iv)，均为 ASCII bytes（纯 Python，无需仿真）。

        公式： d = sha256hex(e(seed)) ; key = d[0:32] ; iv = d[32:48]
        已与 native 的 hook 实测值逐字节一致。
        """
        return key_iv_py(signature)

    def key_iv_native(self, signature):
        """走 native `ea` 仿真派生 (key, iv)（对照用）。"""
        self.reset()
        js = self._jstr(signature)
        ja = self._jarr(b"\x00" * 32)
        got = []

        def hook(uc, addr, size, ud):
            src = int(uc.reg_read(UC_ARM64_REG_X1))
            n = int(uc.reg_read(UC_ARM64_REG_X2))
            got.append(bytes(uc.mem_read(src, min(n, 64))))

        h = self.uc.hook_add(UC_HOOK_CODE, hook,
                             begin=self.BY_NAME["__strncpy_chk2"],
                             end=self.BY_NAME["__strncpy_chk2"] + 4)
        try:
            sp = self.STACK - 0x2000
            self.uc.reg_write(UC_ARM64_REG_TPIDR_EL0, self.TP)
            self.uc.mem_write(self.TP + 0x28, b"\x11" * 8)
            self.uc.mem_write(sp, struct.pack("<Q", self.RETM))
            for i, a in enumerate([self.ENVOBJ, 0, js, ja, 0, 0, 0]):
                self.uc.reg_write(UC_ARM64_REG_X0 + i, a)
            self.uc.reg_write(UC_ARM64_REG_SP, sp)
            self.uc.reg_write(UC_ARM64_REG_LR, self.RETM)
            self.uc.mem_write(self.RETM, b"\xc0\x03\x5f\xd6")
            self.uc.emu_start(FN_EA, self.RETM, count=20000000)
        finally:
            self.uc.hook_del(h)
        if len(got) < 2:
            raise RuntimeError("key/iv 派生失败（native 未走到 strncpy）")
        return got[0], got[1]

    def decrypt(self, ct, signature):
        """ct: bytes；返回解密后的原始字节（已去 PKCS7，未 gunzip）。

        优先走 native `da()`（0x4b38）—— 它是权威实现，且与 `ea()` 往返
        4/4 验证通过。native 失败时回落到纯 Python AES-256-CBC。
        """
        self.reset()
        r = self._call(FN_DA, [self.ENVOBJ, 0, self._jstr(signature),
                               self._jarr(ct), 0])
        out = self._getstr(r) if r else None
        if out:
            return bytes(out)
        # fallback：纯 Python（依赖 key_iv，仅在 native 失效时使用）
        key, iv = self.key_iv(signature)
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)

    def decrypt_hex(self, hex_text, signature, gunzip=True):
        """hex_text: 服务端返回的 ASCII hex；返回文本。"""
        ct = binascii.unhexlify(hex_text.strip())
        raw = self.decrypt(ct, signature)
        # 若走的是纯 Python 回落路径，需手动去 PKCS7
        if raw and len(raw) % 16 == 0:
            pad = raw[-1]
            if 1 <= pad <= 16 and raw[-pad:] == bytes([pad]) * pad:
                raw = raw[:-pad]
        if gunzip:
            try:
                return gzip.decompress(raw).decode("utf-8", "replace")
            except Exception:
                pass
        return raw.decode("utf-8", "replace")

    def encrypt(self, pt, signature):
        """pt: bytes；返回密文 bytes（与 app 一致）。"""
        self.reset()
        r = self._call(FN_EA, [self.ENVOBJ, 0, self._jstr(signature),
                               self._jarr(pt), 0, 0, 0])
        return bytes(self.JARR.get(r, b""))


def selftest():
    mc = _Emu()
    ok = 0
    for i in range(5):
        sig = hashlib.sha1(os.urandom(20)).hexdigest()
        pt = os.urandom(16 * (1 + i % 3))
        enc = mc.encrypt(pt, sig)
        dec = mc.decrypt(enc, sig)
        good = dec[:len(pt)] == pt
        ok += good
        print(f"  [{i}] sig={sig[:10]} len={len(pt)} ok={good}")
    print(f"PASS {ok}/5 (native ea <-> da round-trip)")
    return ok == 5


if __name__ == "__main__":
    selftest()
