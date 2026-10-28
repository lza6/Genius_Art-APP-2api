# Genius Art (gen-ai.amobear.com) 2API — new-api 渠道对接指南

> 逆向自 Genius Art Image AI Generator v1.5.4 (com.aiart.artgenerator.photoeditor.aiimage, ElaMods Premium Mod)

## 架构

```
new-api 渠道(type 自定义) ──> demo_server.py :8907 ──> gen-ai.amobear.com
                                   │
                            frida RPC 加密桥
                                   │
                        模拟器 (openchat AVD, libamg.so)
```

## 上游协议（已验证）

### 1. 获取 JWT（14 天有效）
```
POST https://gen-ai.amobear.com/v5/account/get-token
Content-Type: application/json

{"data":"<AMGUtil.getToken(ctx,'TokenFirbaseTest') 的 native 加密>"}

响应(加密串) → AMGUtil.decrypt →
{"token":"<JWT>","time":<ms>}
```
JWT payload: `{device_id, package_name, firebase_token:"TokenFirbaseTest", iat, exp(+14d)}`
**每次调用 get-token 会随机生成新 device_id → 天然无限号池。**

### 2. 文生图（同步出图！）
```
POST https://gen-ai.amobear.com/v5/tools/prompt-to-image
Authorization: Bearer <JWT>
Content-Type: application/json

{"data":"<encrypt(JSON.stringify({type:'1',tier:'1',prompt:'...'}))>"}

响应 201(加密串) → decrypt →
{"result":{"url":"https://storage.googleapis.com/ai-bucket-v5/....jpg?<GCP签名15分钟>"}}
```
- `tier`: 1/2/3 = 国家分级（美欧/发展中/低付费），实测三档全部可用
- `type`: "1"
- 内容过滤: 敏感词返回 410 `"The photo you choose contains sensitive content..."`
- 出图耗时 8~34s，同 device 10 并发未测出配额上限

## 加密层

`libamg.so` native AES，key 派生自 `assets/dic` + 包名，每次调用含随机 nonce（选择明文分析见 crypto_probe.json）。
当前通过 frida RPC 桥（`rpc_script.js`）调用模拟器内真实实现，无需还原算法。

## 部署 demo_server

```bash
# 1. 模拟器要求: arm64 转译 (openchat AVD), 装 fs16 frida-server
adb install -r -t genius-art.apk
adb shell pm enable com.aiart.artgenerator.photoeditor.aiimage
adb shell settings put global http_proxy 10.0.2.2:10808   # 上游 IPv6 直连会挂
adb root && adb shell nohup /data/local/tmp/fs16 -D &
adb shell am start -n com.aiart.artgenerator.photoeditor.aiimage/.newflow.splash.SplashNewActivity

# 2. 启动服务（挂了会自动 heal 重装）
python demo_server.py emulator-5570 8907

# 3. 测试
curl http://127.0.0.1:8907/v1/images/generations \
  -H "Authorization: Bearer sk-geniusart-demo" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a cat in ghibli style"}'
```

## new-api 渠道配置

| 项 | 值 |
|---|---|
| 类型 | OpenAI 自定义 (images/generations 透传) |
| Base URL | `http://<demo服务器IP>:8907` |
| 密钥 | `sk-geniusart-demo` |
| 模型 | `genius-art`（demo_server 里固定 t2i，按需扩展模型名映射 tier） |
| 备注 | 单图 8-34s，建议超时 ≥60s |

## 已知限制 / 待办

- [ ] frida 桥依赖模拟器存活（heal.py 自动重装可抗卸载，但模拟器崩溃需人工重启）
- [ ] libamg.so AES key 静态提取（摆脱模拟器）— 下一步
- [ ] 其它端点（enhance/remove-bg/ghiblis 等 v5/tools/*）同协议，按需加
- [ ] 模拟器被其它并行会话共用时会互踢包 → 建议 dedicated AVD
