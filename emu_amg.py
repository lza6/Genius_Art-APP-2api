"""Emulate Java_com_android_amg_AMGUtil_getToken (arm64) in Unicorn.
Runs the native function directly on x86_64 Windows — no emulator needed.
Hook JNI functions (GetStringUTFChars / NewStringUTF) at the Python boundary."""
import unicorn, struct, lief, sys, json

LIB = 'D:/apk-analysis/genius-art/apk_raw/lib/arm64-v8a/libamg.so'
b = lief.parse(LIB)
IMG_BASE = 0x4000000

# map PT_LOAD segments
mu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_LITTLE_ENDIAN)
segs = []
for seg in b.segments:
    if str(seg.type) == 'Segment.TYPE.LOAD' or 'LOAD' in str(seg.type):
        segs.append(seg)
maxaddr = 0
for seg in segs:
    va = IMG_BASE + seg.virtual_address
    sz = seg.virtual_size
    data = bytes(seg.content)
    mu.mem_map(va & ~0xFFF, ((va & 0xFFF) + max(sz, len(data)) + 0xFFF) & ~0xFFF)
    mu.mem_write(va, data)
    maxaddr = max(maxaddr, va + sz)

STACK = 0x7f000000
mu.reg_write(unicorn.arm64_const.UC_ARM64_REG_SP, STACK)
mu.mem_map(STACK - 0x100000, 0x200000)

HEAP = 0x60000000
heap_ptr = HEAP
mu.mem_map(HEAP, 0x1000000)

def alloc(bytes_or_str):
    global heap_ptr
    if isinstance(bytes_or_str, str):
        bytes_or_str = bytes_or_str.encode()
    p = heap_ptr
    mu.mem_write(p, bytes_or_str + b'\x00')
    heap_ptr += len(bytes_or_str) + 16
    return p

# --- JNI env fake: we intercept calls into it ---
# JNIEnv* = pointer to function table. Table slots used by libamg (from strings):
#   GetStringUTFChars, NewStringUTF, GetStringLength etc. We'll build a table where
# each slot points to a magic address; hook UC_HOOK_CODE at those to emulate.
JNI_TABLE = 0x50000000
mu.mem_map(JNI_TABLE, 0x10000)
ENV_PTR = JNI_TABLE  # JNIEnv* -> table

MAGIC_BASE = 0x52000000
mu.mem_map(MAGIC_BASE, 0x10000)
slot_map = {}   # magic addr -> index
for i in range(300):
    a = MAGIC_BASE + i * 8
    mu.mem_write(JNI_TABLE + i * 8, struct.pack('<Q', a))
    slot_map[a] = i

env_ptr_p = alloc(struct.pack('<Q', ENV_PTR))     # JNIEnv**
# JavaVM* table: GetEnv at index 6*8=0x30 (JNI: GetEnv is index 6 in JNIInvokeInterface)
VM_TABLE = 0x53000000
mu.mem_map(VM_TABLE, 0x10000)
vm_ptr_p = alloc(struct.pack('<Q', VM_TABLE))
java_vm = VM_TABLE  # JavaVM*

ret_vals = {}
log = []

from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X8, UC_ARM64_REG_PC

FN = {
    'getToken': 0x29fa8,
}

def hook_code(mu, address, size, user_data):
    if MAGIC_BASE <= address < MAGIC_BASE + 0x10000:
        idx = (address - MAGIC_BASE) // 8
        log.append(('jni_call', idx))
        # default: return 0
        mu.reg_write(UC_ARM64_REG_X0, 0)

mu.hook_add(unicorn.UC_HOOK_CODE, hook_code)

def run(fn_off, args, timeout=10_000_000):
    """Call arm64 fn(args...) — args up to 8 (x0..x7). Returns x0. Handles JNI via hook."""
    RET_MAGIC = 0x5f000000
    mu.mem_map(RET_MAGIC, 0x1000)
    sp = STACK - 0x1000
    mu.reg_write(unicorn.arm64_const.UC_ARM64_REG_SP, sp)
    for i, a in enumerate(args[:8]):
        mu.reg_write(UC_ARM64_REG_X0 + i, a)
    mu.reg_write(unicorn.arm64_const.UC_ARM64_REG_LR, RET_MAGIC)
    try:
        mu.emu_start(IMG_BASE + fn_off, RET_MAGIC, timeout=timeout)
    except unicorn.UcError as e:
        pc = mu.reg_read(unicorn.arm64_const.UC_ARM64_REG_PC)
        return ('ERROR', hex(pc), str(e), log[-10:])
    return mu.reg_read(UC_ARM64_REG_X0)

# --- attempt: getToken(env, clazz, ctx, keystr) — but it calls JNI to build strings.
# The lib uses C++ std::string (files) and likely GetStringUTFChars etc.
# First we need JNI table indices the lib actually calls. Do a dry run and log indices.
ctx_obj = alloc(b'fakectx')  # jobject
keystr = alloc('TokenFirbaseTest')  # jstring (fake — real one is Java object; lib will call JNI on it)
res = run(FN['getToken'], [ENV_PTR, 0, ctx_obj, keystr])
print('getToken result:', res)
print('JNI calls (first 30):', [x[1] for x in log[:30]])
json.dump({'calls': [x[1] for x in log]}, open('jni_calls.json', 'w'))
