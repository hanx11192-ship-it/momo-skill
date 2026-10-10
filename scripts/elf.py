"""Shared ELF loader for libmomoco.so: vaddr<->file offset, relocations, dynsym."""
import os
import struct

_HERE = os.path.dirname(os.path.abspath(__file__))
SO = open(os.path.join(_HERE, 'libmomoco.so'), 'rb').read()

def _hdr():
    e_shoff = struct.unpack_from('<Q', SO, 0x28)[0]
    e_shentsize = struct.unpack_from('<H', SO, 0x3a)[0]
    e_shnum = struct.unpack_from('<H', SO, 0x3c)[0]
    e_shstrndx = struct.unpack_from('<H', SO, 0x3e)[0]
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, typ, flags, addr, off, size, link, info, align, entsize = \
            struct.unpack_from('<IIQQQQIIQQ', SO, o)
        secs.append(dict(name=name, addr=addr, off=off, size=size, link=link, entsize=entsize))
    shstr = secs[e_shstrndx]
    def nm(x):
        e = SO.index(b'\x00', shstr['off'] + x)
        return SO[shstr['off'] + x:e].decode()
    for s in secs:
        s['n'] = nm(s['name'])
    return secs

SECS = _hdr()
BYNAME = {s['n']: s for s in SECS}

def v2o(vaddr):
    for s in SECS:
        if s['addr'] and s['size'] and s['addr'] <= vaddr < s['addr'] + s['size'] and s['n'] not in ('',):
            return s['off'] + (vaddr - s['addr'])
    return None

def o2v(off):
    for s in SECS:
        if s['off'] and s['size'] and s['off'] <= off < s['off'] + s['size']:
            return s['addr'] + (off - s['off'])
    return None

def rd(vaddr, n):
    o = v2o(vaddr)
    if o is None:
        # fall back: identity (some rodata overlaps)
        o = vaddr
    return SO[o:o + n]

def rdstr(vaddr):
    o = v2o(vaddr)
    if o is None:
        o = vaddr
    e = SO.index(b'\x00', o)
    return SO[o:e].decode('utf-8', 'replace')

def dynsyms():
    ds = BYNAME['.dynsym']; dstr = BYNAME['.dynstr']
    out = []
    for i in range(ds['size'] // 24):
        o = ds['off'] + i * 24
        nameoffs, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', SO, o)
        e = SO.index(b'\x00', dstr['off'] + nameoffs)
        out.append((SO[dstr['off'] + nameoffs:e].decode(), value, size))
    return out

def relocations():
    """Return list of (kind, offset, symname, addend). kind in {'plt','rel'}"""
    syms = dynsyms()
    res = []
    for sn, kind in (('.rela.dyn', 'rel'), ('.rela.plt', 'plt')):
        s = BYNAME[sn]
        for i in range(s['size'] // 24):
            o = s['off'] + i * 24
            roff, rinfo, radd = struct.unpack_from('<QQq', SO, o)
            stype = rinfo & 0xffffffff
            ssym = rinfo >> 32
            res.append((kind, roff, stype, syms[ssym][0], radd))
    return res

def jni_methods():
    """Decode the JNINativeMethod[] table in .data (base 0x11a88).

    .data is all zeros in the file; values come from .rela.dyn
    R_AARCH64_RELATIVE (1027) relocations.  Entries are 24-byte
    {name_ptr, sig_ptr, fn_ptr} but NOT contiguous -- interleaved with
    an 8-byte back-pointer + 8-byte count.  Use a sliding 8-byte window
    with validation instead of a fixed stride.
    """
    mem = bytearray(SO)
    for kind, roff, stype, sym, addend in relocations():
        if stype == 1027:  # R_AARCH64_RELATIVE
            o = v2o(roff)
            if o is not None:
                struct.pack_into('<Q', mem, o, addend)
    d = BYNAME['.data']
    buf = bytes(mem[d['off']:d['off'] + d['size']])
    base = d['addr']

    def cstr(v):
        if not (0x1000 <= v < 0x20000):
            return None
        o = v2o(v)
        if o is None:
            return None
        e = SO.find(b'\x00', o)
        if e < 0 or e - o > 120:
            return None
        try:
            return SO[o:e].decode('ascii')
        except Exception:
            return None

    res = []
    for k in range(0, len(buf) - 24 + 1, 8):
        np_, sp_, fp_ = struct.unpack_from('<QQQ', buf, k)
        if not (0x1000 <= np_ < 0x20000 and 0x1000 <= sp_ < 0x20000
                and 0x3000 <= fp_ < 0x10000):
            continue
        nm, sg = cstr(np_), cstr(sp_)
        if not nm or not sg or not sg.startswith('(') or len(nm) > 20:
            continue
        if not nm.replace('_', '').isalnum():
            continue
        res.append((nm, sg, fp_))
    return res

def rdstr_or(vaddr, mem):
    o = v2o(vaddr)
    e = mem.index(b'\x00', o)
    return mem[o:e].decode('utf-8', 'replace')

if __name__ == '__main__':
    print('=== JNINativeMethod ===')
    for n, s, f in jni_methods():
        print(f'{hex(f):>8}  {n!r:30} {s!r}')
