如果你说的 **GUI Grounding** 是：

> 输入一张软件截图 + 自然语言（例如："点击右上角设置按钮"），模型返回 **按钮bbox或者(x,y)坐标**，而不是仅仅OCR或描述图片。

那么目前属于 **Computer Use Agent (CUA)** 或 **GUI Grounding VLM** 这一类模型。

## 目前商业SOTA

| 模型                       | 精确定位 | bbox | point | Computer Use | 是否API      |
| ------------------------ | ---- | ---- | ----- | ------------ | ---------- |
| bytedance/ui-tars-1.5-7b | ✅    | ✅    | ✅     | ✅            | OpenRouter |
| UI-TARS-72B              | ✅    | ✅    | ✅     | ✅            | OpenRouter |
| Claude Computer Use      | ✅    | ✅    | ✅     | ✅            | Anthropic  |
| OpenAI Computer Use      | ✅    | ✅    | ✅     | ✅            | OpenAI     |
| Gemini Computer Use      | ✅    | 部分   | ✅     | ✅            | Vertex AI  |
| Qwen3-VL Agent           | ✅    | ✅    | ✅     | ✅            | 阿里         |
| GPT-5 Computer Use       | ✅    | ✅    | ✅     | ✅            | 企业版        |

其中 UI-TARS 被认为是目前开源阵营里非常强的 GUI Grounding 模型之一。([OpenRouter][1])

---

# 开源免费的有哪些？

近一年 GUI Grounding 开源模型发展非常快，目前比较值得关注的有：

| 模型             | 参数    | 开源 | GUI Grounding | 推荐程度  |
| -------------- | ----- | -- | ------------- | ----- |
| UI-TARS-1.5-7B | 7B    | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |
| UI-TARS-72B    | 72B   | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |
| OS-Atlas       | 7B/8B | ✅  | ⭐⭐⭐⭐          | ★★★★  |
| ShowUI         | 7B    | ✅  | ⭐⭐⭐⭐          | ★★★★  |
| SeeClick       | 7B    | ✅  | ⭐⭐⭐⭐          | ★★★★  |
| CogAgent       | 18B   | ✅  | ⭐⭐⭐⭐          | ★★★★  |
| Aria-UI        | 8B    | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |
| UI-Venus       | 8B    | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |
| UGround        | 7B    | ✅  | ⭐⭐⭐⭐          | ★★★★  |
| MEGA-GUI       | 8B    | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |
| Phi-Ground     | <10B  | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |
| POINTS-GUI-G   | 8B    | ✅  | ⭐⭐⭐⭐⭐         | ★★★★★ |

其中不少模型是在 ScreenSpot、OSWorld-G、AndroidWorld 等 GUI Grounding 基准上与 UI-TARS 竞争的新一代开源模型。([perea.ai][2])

---

# OpenRouter 上有哪些支持 GUI Grounding？

截至目前，真正定位于 GUI Agent / GUI Grounding 的并不多。

| OpenRouter模型                       | GUI定位                                    | 收费                               |
| ---------------------------------- | ---------------------------------------- | -------------------------------- |
| bytedance/ui-tars-1.5-7b           | ✅                                        | **收费**（约$0.10/M输入，$0.20/M输出）     |
| bytedance-research/ui-tars-72b     | ✅                                        | **有免费版本 (`:free`)**，也有收费Provider |
| Claude Sonnet/Opus（Computer Use能力） | 可以完成GUI任务，但不是专门输出bbox                    | 收费                               |
| Gemini 2.5 Pro/Flash               | 可做视觉推理，GUI能力不错，但非专门grounding接口           | 收费                               |
| Qwen3-VL系列                         | 有GUI理解能力，但OpenRouter版本通常未专门暴露grounding输出 | 收费                               |

其中：

* **`bytedance/ui-tars-1.5-7b`**：目前OpenRouter上最成熟的GUI Grounding模型之一，支持坐标预测和GUI操作规划。([OpenRouter][1])
* **`bytedance-research/ui-tars-72b:free`**：提供免费访问（通常有速率限制和排队），适合测试；正式生产建议使用收费Provider。([OpenRouter][3])

---

## OpenRouter 免费可用情况

| 模型                         | 免费 |
| -------------------------- | -- |
| bytedance/ui-tars-72b:free | ✅  |
| bytedance/ui-tars-72b      | ❌  |
| bytedance/ui-tars-1.5-7b   | ❌  |
| Claude系列                   | ❌  |
| Gemini系列                   | ❌  |
| GPT系列                      | ❌  |

严格来说，**OpenRouter 上目前真正免费的 GUI Grounding 模型基本就是 `ui-tars-72b:free`**，其他专门GUI定位模型大多需要付费或自行部署。

---

# 如果你要做「截图→按钮坐标」服务，我推荐如下方案

| 方案                         | 精度    | 成本    | 推荐       |
| -------------------------- | ----- | ----- | -------- |
| UI-TARS-1.5-7B（OpenRouter） | ⭐⭐⭐⭐⭐ | 很低    | ⭐⭐⭐⭐⭐    |
| UI-TARS-72B:free           | ⭐⭐⭐⭐⭐ | 免费    | ⭐⭐⭐⭐（限流） |
| 本地部署 UI-TARS-1.5-7B        | ⭐⭐⭐⭐⭐ | GPU成本 | ⭐⭐⭐⭐⭐    |
| Phi-Ground-8B              | ⭐⭐⭐⭐⭐ | 本地    | ⭐⭐⭐⭐     |
| POINTS-GUI-G-8B            | ⭐⭐⭐⭐⭐ | 本地    | ⭐⭐⭐⭐     |
| Claude Computer Use        | ⭐⭐⭐⭐⭐ | 较高    | ⭐⭐⭐      |
| GPT Computer Use           | ⭐⭐⭐⭐⭐ | 较高    | ⭐⭐⭐      |

对于你之前提到的 **把 Kaggle/Colab GPU 推理通过 tunnel 暴露成 endpoint** 的场景，**本地部署 UI-TARS-1.5-7B 或 Phi-Ground-8B，再输出标准化 JSON（如 `{x, y}` 或 `{bbox: [...]}`）会是性价比最高的方案**：既能获得像商业 Computer Use 模型那样的 GUI 元素精确定位能力，又可以完全控制接口格式和访问权限。

[1]: https://openrouter.ai/bytedance/ui-tars-1.5-7b/playground?utm_source=chatgpt.com "ByteDance: UI-TARS 7B – Playground | OpenRouter"
[2]: https://www.perea.ai/research/gui-grounding-models-2026?utm_source=chatgpt.com "GUI Grounding Models 2026 | Perea.AI"
[3]: https://openrouter.ai/bytedance-research/ui-tars-72b%3Afree/api?utm_source=chatgpt.com "Bytedance: UI-TARS 72B – API Quickstart | OpenRouter"
