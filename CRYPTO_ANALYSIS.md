# libamg.so 密码学分析（静态提取进行中）

## 已确认结构

### 密文布局（base64 解码后）
```
[16B session header] [enc body: nonce + pt + ~208B 内嵌元数据]
- header 会话内恒定（进程 init 时派生），跨进程变化
- body 每次调用不同（内嵌随机 nonce，来源 = SVC getrandom syscall）
- overhead 恒定 240B（pt=0 时密文 256B）：16 hdr + 16 nonce? + 208 元数据
- 长度公式: ct_len = 240 + 16*ceil((pt_len+2)/16)
```

### 硬编码 32B 密钥材料（0x21748 指令流逐字节构造）

```
array_A (x29-0x18..x29-0x09, 16B): 2195408f3ef080a6b46256b205e700d5
array_B (sp+0x28..sp+0x37,  16B): 80813b997372dd3ddb2aa388c3c1c788
组合 candidate key32 = array_A || array_B
```
- `assets/dic`（4016B，加密）= 真实 key 材料，lib init 时 fopen 一次 → 全局
- 上述 32B 是代码内常数（可能是 KDF salt 或 fallback key）

### 已识别的算法痕迹
| 地址 | 特征 | 推断 |
|---|---|---|
| 0x24ab8 | 检查 `=`(0x3d)，逐字节查表 | base64 decode |
| 0x220c4 | 4×32bit BE word 与 state XOR | ChaCha20/Salsa 风格流密码核 |
| 0x249cc / 0x255c8 / 0x213b0 | 未识别 Rust crypto crate | hash/HMAC/AES |

### JNI 入口
| 函数 | 偏移 |
|---|---|
| encrypt | 0x290e8 → pre 0x28ffc → 核心 0x289b8 |
| decrypt | 0x29ae8 |
| getToken | 0x29fa8（= encrypt("TokenFirbaseTest") 变体） |

## 离线复现路线（可行，待实施）
1. Unicorn 映射 PT_LOAD + TLS (tpidr_el0) + 栈/堆
2. Hook: SVC intr（getrandom → 喂固定值）+ fopen（喂 assets/dic 真实内容）+ JNI 表 slot
3. 调 0x29fa8 / 0x290e8 直接拿输入输出对
4. 已有 unicorn 脚手架: emu_amg.py（当前崩在 TLS 0x29fb8）
5. 服务端接受任意 nonce → 只需保证 key 正确即可构造合法请求

## 备选：保持 frida 桥（当前生产方案）
- demo_server.py + heal.py 自动保活，专用 AVD (emulator-5570)
- 稳定性已验证（压测 R1 8/8 + R3 10并发）
