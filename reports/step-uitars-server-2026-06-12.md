# Step UI-TARS Server 测试报告

## 测试环境
- 日期：2026-06-12
- 版本：git commit `0e275de`
- 推理服务：`http://192.168.3.14:8000`（llama-cpp-python 0.3.19 + GGUF Q4_K_M + mmproj q8_0）
- 本地 Python：`.venv` (Python 3.14.3, pytest 9.0.3)

---

## 单元测试结果（test_inference_client_unit.py）

不依赖推理服务，不产生持久数据。

| Case ID | 描述 | 结果 | 耗时 |
|---------|------|------|------|
| UNIT-01 | parse_action_simple: click 基本格式 | ✅ PASS | - |
| UNIT-02 | parse_action_simple: click + box_token | ✅ PASS | - |
| UNIT-03 | parse_action_simple: click + Thought 前缀 | ✅ PASS | - |
| UNIT-04 | parse_action_simple: left_double → double_click | ✅ PASS | - |
| UNIT-05 | parse_action_simple: right_single → right_click | ✅ PASS | - |
| UNIT-06 | parse_action_simple: type 英文 | ✅ PASS | - |
| UNIT-07 | parse_action_simple: type 中文 | ✅ PASS | - |
| UNIT-08 | parse_action_simple: scroll + direction | ✅ PASS | - |
| UNIT-09 | parse_action_simple: hotkey | ✅ PASS | - |
| UNIT-10 | parse_action_simple: finished | ✅ PASS | - |
| UNIT-11 | parse_action_simple: 2560×1440 坐标映射 | ✅ PASS | - |
| UNIT-12 | parse_action_simple: 不可解析返回 None | ✅ PASS | - |
| UNIT-13 | parse_action_simple: 坐标在图像边界内 | ✅ PASS | - |
| UNIT-14 | encode_image: bytes 输入 | ✅ PASS | - |
| UNIT-15 | encode_image: BytesIO 输入 | ✅ PASS | - |
| UNIT-16 | encode_image: PIL Image 输入 | ✅ PASS | - |
| UNIT-17 | encode_image: 文件路径输入 | ✅ PASS | - |
| UNIT-18 | add_box_token: 坐标加 token | ✅ PASS | - |
| UNIT-19 | add_box_token: 无 action 原样返回 | ✅ PASS | - |
| UNIT-20 | add_box_token: 已有 token 不重复包裹 | ✅ PASS | - |

### pytest 输出摘要（单元）
```
pytest automation/tests/test_inference_client_unit.py -v
20 passed in 0.56s
```

### Bug Fix 记录
- **encode_image PIL 延迟加载问题**：PIL `Image.open()` 是懒加载，`save()` 触发 `_ensure_mutable()` 时底层 fp 可能已 None。Fix：`save()` 前调用 `source.load()` 强制加载像素数据。
- **测试 fixture PNG 损坏**：Base64 硬编码的 1×1 PNG 在新版 Pillow（11.x）下 IDAT 解码失败。Fix：改用 struct/zlib 程序生成 2×2 RGB PNG。

---

## 集成测试结果（test_uitars_server_integration.py）

依赖 `192.168.3.14:8000` 推理服务在线，服务不可达时自动 skip。

| Case ID | 描述 | 结果 | 备注 |
|---------|------|------|------|
| INT-01 | GET /v1/models 返回非空列表 | ✅ PASS | - |
| INT-02 | 模型 ID 是 GGUF 文件路径 | ✅ PASS | `/models/UI-TARS-1.5-7B-q4_k_m.gguf` |
| INT-03 | 空闲 GPU 显存 < 8192 MiB | ✅ PASS | flash_attn 优化后约 5012 MiB |
| INT-04 | 小图（100×100）推理有输出 | ✅ PASS | - |
| INT-05 | 标准 viewport（1280×720）推理有输出 | ✅ PASS | - |
| INT-06 | 1280×720 返回 click 动作 | ✅ PASS | - |
| INT-07 | click 坐标在图像范围内 | ✅ PASS | - |
| INT-08 | 蓝色按钮（x=100-300）预测在左半区 | ✅ PASS | - |
| INT-09 | 2560×1440 全分辨率推理成功（不 OOM） | ✅ PASS | n_ctx=8192 + flash_attn |
| INT-10 | 2560×1440 推理后显存峰值 < 11000 MiB | ✅ PASS | 实测 **7910 MiB** / 12288 MiB |

### pytest 输出摘要（集成）
```
pytest automation/tests/test_uitars_server_integration.py -v -s
10 passed in 25.88s

  GPU 显存实测: 7910 MiB / 12288 MiB
```

---

## 关键技术参数（实测）

| 参数 | 数值 |
|------|------|
| 模型 | UI-TARS-1.5-7B-q4_k_m.gguf |
| Vision projector | UI-TARS-1.5-7B-q8_0.mmproj |
| n_ctx | 8192 |
| flash_attn | true |
| 空闲显存 | ~5012 MiB |
| 2560×1440 推理峰值显存 | **7910 MiB** |
| GPU 总显存 | 12288 MiB（RTX 3060） |
| 推理延迟（2560×1440） | ~25s（64 tokens） |

---

## 已知问题

无。所有 30 个 case 全部 PASS。
