# Genius Art 2API (gen-ai.amobear.com)

逆向 Genius Art Image AI Generator v1.5.4 (ElaMods Mod) 的 t2i 全链路，OpenAI 兼容 demo + new-api 渠道对接。

## 真图证据

| Ghibli cat | Ukiyo-e samurai cat |
|---|---|
| ![ghibli](examples/ghibli_cat.jpg) | ![samurai](examples/samurai_cat.jpg) |

## 快速开始

见 [NEWAPI_CHANNEL_GUIDE.md](NEWAPI_CHANNEL_GUIDE.md)

## 压测结论 (R1)

| 场景 | 结果 |
|---|---|
| 4 并发 × 8 prompt | 8/8 成功, p50 32s |
| 同 device 10 并发 | 全 201，无配额上限 |
| 错误处理 | 401/400/410(内容过滤) 正常 |
| 号池 | get-token 随机 device_id, JWT 14 天, 天然无限 |
