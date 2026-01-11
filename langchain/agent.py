from langchain_core.messages import HumanMessage

from _agent import get_app

app = get_app()

result = app.invoke({
    "messages": [
            #("user", "帮我查一下AI项目的资料，分析一下可行性，然后生成一份简要报告")
            HumanMessage(content="帮我查一下AI项目的资料，分析可行性，并生成简要报告")
    ]
})

print("\n--- 最终输出 ---\n")
print("len(result['messages']) == ", len(result["messages"]))
print(result["messages"][-1].content)

# 没有优化tool注释以前
"""
test1, siliconflow, LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Qwen-7B
len(result["messages"]) == 1
--- 最终输出 ---

为了为您提供一份有价值的可行性分析报告，我需要先明确您关注的具体**AI项目方向**或**具体内容**。因为“AI项目”涵盖的范围非常广（从自动驾驶、医疗诊断到聊天机器人、AI绘画等）。

请您补充一下您具体想了解的**关键词**或**项目描述**。您可以参考以 下几个维度提供信息：

1.  **具体行业/场景**：例如“AI在跨境电商客服中的应用”、“AI辅助法律合同审查”、“智慧农业病虫害识别”。
2.  **特定技术方向**：例如“基于RAG的企业知识库”、“边缘计 算AI芯片”、“多模态大模型应用”。
3.  **如果您有一个具体的创业/项目点子**：请简单描述该项目的功能和目标用户。

---

**一旦您提供了具体方向，我将立即执行以下流程为您生成报告 ：**

1.  **调用 `search_doc`**：针对您提供的关键词，检索最新的市场趋势、技术成熟度、主要竞品及相关政策风险。
2.  **调用 `analyze_data`**：对检索到的信息进行SWOT分析（优势、劣势、机会、威胁），评估技术落地难度和市场潜力。   
3.  **调用 `generate_report`**：汇总上述信息，生成一份包 含“项目背景、核心竞争力、风险提示、结论建议”的简要可行性 报告。

**请告诉我您想查询的具体项目或方向：**


test2, siliconflow, LLM_MODEL=Pro/deepseek-ai/DeepSeek-R1
len(result["messages"]) == 1
--- 最终输出 ---

由于“AI项目”的范围非常广泛（涵盖了从大语言模型应用、计算机视觉、自动 驾驶到具体的行业解决方案等众多领域），为了能为您提供有价值的分析和报 告，**我需要您提供更具体的方向或关键词**。

例如，您可以告诉我：
1.  **具体场景**：例如“企业内部AI知识库”、“电商AI客服”、“AI生成短视频”、“医疗影像分析”等。
2.  **目标人群**：是面向C端用户（大众）还是B端企业？
3.  **核心技术**：例如“基于ChatGPT开发”、“使用Stable Diffusion绘图”等。

---

为了展示我的工作流程，我将先以目前市场上最热门的 **“企业级RAG（检索增强生成）私有知识库项目”** 为例，为您模拟一次完整的 **资料查询、分析与报告生成** 过程。

### ⏳ 正在执行：模拟工作流

1.  **调用 `search_doc`**：查询“RAG技术趋势”、“企业AI知识库市场规模” 、“LangChain开发成本”、“数据隐私合规”。
2.  **调用 `analyze_data`**：对比开源方案（如LlamaIndex, LangChain） 与商业方案（如百度千帆, OpenAI Assistant）的优劣势；分析算力成本与部 署难度。
3.  **调用 `generate_report`**：汇总信息，生成以下简报。

---

### 📄 示例报告：企业级RAG私有知识库项目可行性分析

#### 1. 项目背景
利用大语言模型（LLM）结合企业私有数据（文档、Wiki、代码），构建“不仅 懂通用知识，更懂企业内部业务”的智能问答助手，解决通用模型（如GPT-4） 无法回答企业内部具体问题且存在数据泄露风险的痛点。

#### 2. 市场与需求分析
*   **需求痛点**：企业文档检索效率低，员工培训成本高，通用AI不懂内部 业务。
*   **市场趋势**：2024年是RAG架构落地的爆发期，几乎所有数字化程度高的企业（金融、法律、IT、客服）都有此需求。

#### 3. 技术可行性 (High)
*   **成熟度**：技术栈（LangChain, LlamaIndex, 向量数据库）已非常成熟。
*   **模型选择**：
    *   *高隐私需求*：可本地部署开源模型（如Qwen-72B, Llama-3）。    
    *   *低成本快速验证*：可调用API（GPT-4o, Claude 3.5, 文心一言）。
*   **开发难度**：中等。核心难点在于“文档切片策略”和“检索准确率优化” ，而非模型训练。

#### 4. 经济可行性 & 成本
*   **初期投入**：较低。无需昂贵的预训练（Pre-training）成本，主要是 微调（Fine-tuning）或推理成本。
*   **运营成本**：取决于Token消耗量或GPU服务器租赁费用。
*   **ROI（投资回报率）**：高。能显著降低客服人力成本和内部信息检索时间。

#### 5. 风险评估
*   **幻觉问题**：模型可能会基于错误的检索内容一本正经地胡说八道（需 引入引用溯源机制）。
引入引用溯源机制）。
*   **数据安全**：若使用云端API，需确保企业核心机密已脱敏或签署隐私协议。

#### 6. 结论与建议
#### 6. 结论与建议
*   **结论**：**极具可行性**。是目前AI落地最快、价值最清晰的赛道之一 *   **结论**：**极具可行性**。是目前AI落地最快、价值最清晰的赛道之一 。
。
*   **建议**：建议从“非核心业务”的小范围场景（如IT帮助台、HR政策问答 ）切入，跑通MVP（最小可行性产品）后再推广至全公司。
*   **建议**：建议从“非核心业务”的小范围场景（如IT帮助台、HR政策问答 ）切入，跑通MVP（最小可行性产品）后再推广至全公司。
）切入，跑通MVP（最小可行性产品）后再推广至全公司。


---
---

### 🟢 轮到您了


test3, openrouter, 
# LLM_MODEL=google/gemini-3-pro-preview
# LLM_MODEL=anthropic/claude-opus-4.5
# LLM_MODEL=openai/gpt-5.2
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.antigravity\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 52034 -- d:\\shouxieagent\\langchain\\agent.py
Traceback (most recent call last):
  File "d:\shouxieagent\langchain\agent.py", line 52, in <module>
    result = app.invoke({
             ^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\pregel\main.py", line 3068, in invoke
    for chunk in self.stream(
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\pregel\main.py", line 2643, in stream
    for _ in runner.tick(
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\pregel\_runner.py", line 167, in tick
    run_with_retry(
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\pregel\_retry.py", line 42, in run_with_retry
    return task.proc.invoke(task.input, config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\_internal\_runnable.py", line 656, in invoke
    input = context.run(step.invoke, input, config, **kwargs)        
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^        
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\_internal\_runnable.py", line 400, in invoke
    ret = self.func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "d:\shouxieagent\langchain\agent.py", line 30, in agent_node  
    "messages": [llm.invoke(state["messages"])]
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_core\runnables\base.py", line 5557, in invoke
    return self.bound.invoke(
           ^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_core\language_models\chat_models.py", line 402, in invoke
    self.generate_prompt(
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_core\language_models\chat_models.py", line 1121, in generate_prompt        
    return self.generate(prompt_messages, stop=stop, callbacks=callbacks, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_core\language_models\chat_models.py", line 931, in generate
    self._generate_with_cache(
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_core\language_models\chat_models.py", line 1225, in _generate_with_cache   
    result = self._generate(
             ^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_openai\chat_models\base.py", line 1380, in _generate
    raise e
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langchain_openai\chat_models\base.py", line 1375, in _generate
    raw_response = self.client.with_raw_response.create(**payload)   
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   
  File "d:\conda_envs\shouxieagent\Lib\site-packages\openai\_legacy_response.py", line 364, in wrapped
    return cast(LegacyAPIResponse[R], func(*args, **kwargs))
                                      ^^^^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\openai\_utils\_utils.py", line 286, in wrapper
    return func(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\openai\resources\chat\completions\completions.py", line 1192, in create
    return self._post(
           ^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\openai\_base_client.py", line 1259, in post
    return cast(ResponseT, self.request(cast_to, opts, stream=stream, stream_cls=stream_cls))
                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\openai\_base_client.py", line 1047, in request
    raise self._make_status_error_from_response(err.response) from None
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Provider returned error', 'code': 400, 'metadata': {'raw': '{\n  "error": {\n    "message": "No tool call found for function call output with call_id call_Zeyp0omqvriDOTpFQFIaYQZr.",\n    "type": "invalid_request_error",\n    "param": "input",\n    "code": null\n  }\n}', 'provider_name': 'OpenAI'}}, 'user_id': 'user_3484NLh7alU2lvDialBWaqxCutU'}  
During task with name 'agent' and id '0bc77ead-282c-59f6-3dce-3af7fdbe1cda'


test3, openrouter, LLM_MODEL=deepseek/deepseek-r1-0528
len(result["messages"]) == 1
--- 最终输出 ---

您的AI项目报告已成功生成！报告整合了关于项目的核心目标、技术框架、实 施阶段、团队协作、成果总结以及未来发展方向等关键信息。以下为报告中的 主要建议：

1. **技术优化**：建议进一步优化机器学习算法模型，提高数据处理效率和决策准确度。
2. **行业扩展**：探索更多行业应用场景（如医疗、金融或教育），以扩大项目的影响力。
3. **用户反馈强化**：持续收集并分析用户反馈，迭代项目功能以提升用户体验。

如果您需要修改报告内容、获取详细数据或进行其他操作，请随时告诉我！   

"""


# 优化tool注释以后
"""
test1, siliconflow, LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Qwen-7B
len(result["messages"]) == 1
--- 最终输出 ---

len(result['messages']) ==  1


好的，我将按照您的要求帮助您完成以下任务：查找AI项目的资料、分析其 可行性，并生成简要报告。以下是操作步骤：

1. **获取AI项目资料**：调用 `search_doc` 函数，搜索与AI项目相关的文档和资料。
2. **分析可行性**：调用 `analyze_data` 函数，对收集到的资料进行深入分析。
3. **生成报告**：调用 `generate_report` 函数，将分析结果汇总为简要 报告。

以下是生成的综合分析报告：

```json
{
  "background": "您的AI项目涉及[简要描述项目背景]，目前处于[项目阶 段]。该项目的目标是[简要描述目标]，预期的市场应用领域包括[简要描述 应用领域]。",
  "technical Feasibility": "根据当前技术发展，AI技术在[具体技术领域]上已较为成熟。项目所需的核心技术包括[简要描述核心技术]，这些技术在[来源]和[来源]中有详细说明。",
  "market Demand": "市场对AI技术的需求呈现增长趋势。根据[市场调研机构]的报告，未来[时间段]内，AI技术的市场规模预计将以[年增长率]增长。项目的目标客户群体包括[简要描述客户群体]，这与当前市场需求高度契合 。",
  "resource Requirements": "项目需要的技术资源包括[简要描述资源需求]，这些资源的获取和配置在[相关文档]中已有详细说明。项目团队需要具备[简要描述技术能力]，而目前团队的组成和能力评估在[团队评估报告]中进 行了全面分析。",
  "risk Analysis": "项目面临的主要风险包括[简要描述风险]。这些风险 可以通过[具体措施]进行有效管理和规避。项目失败的可能性评估在[风险评估报告]中进行了详细分析。",
  "conclusion": "总体来看，该项目具有较高的技术可行性、市场需求和商业潜力。建议在[具体措施]的基础上，进一步加强[具体措施]，以提高项目 的成功概率。",
  "recommendations": [
    "建议在[时间段]内加速[具体任务]的推进，以提升项目的执行效率。",
    "建议在[预算范围内]增加[具体资源]的投入，以进一步优化项目方案。",
    "建议与[合作伙伴]建立合作关系，以共享资源和经验，提升项目成功率。"
  ]
}
```

### 详细步骤说明：
1. **调用 `search_doc` 函数**：
   ```json
   {
     "function": "search_doc",
     "parameters": {
       "query": "AI项目可行性分析"
     }
   }
   ```
   - 这一步将搜索与AI项目相关的文档和资料，包括技术文档、市场报告和行业分析。

2. **调用 `analyze_data` 函数**：
   ```json
   {
     "function": "analyze_data",
     "parameters": {
       "data": "收集到的资料内容"
     }
   }
   ```
   - 这一步将分析搜索到的资料，评估项目的背景、技术可行性、市场需求、资源需求和风险。

3. **调用 `generate_report` 函数**：
   ```json
   {
   ```
   - 这一步将分析搜索到的资料，评估项目的背景、技术可行性、市场需求、资源需求和风险。

3. **调用 `generate_report` 函数**：
   ```json
   {
   - 这一步将分析搜索到的资料，评估项目的背景、技术可行性、市场需求、资源需求和风险。

3. **调用 `generate_report` 函数**：
   ```json
   {
、资源需求和风险。

3. **调用 `generate_report` 函数**：
   ```json
   {

3. **调用 `generate_report` 函数**：
   ```json
   {
3. **调用 `generate_report` 函数**：
   ```json
   {
     "function": "generate_report",
     "parameters": {
   ```json
   {
     "function": "generate_report",
     "parameters": {
       "content": "分析结果内容"
   {
     "function": "generate_report",
     "parameters": {
       "content": "分析结果内容"
     }
     "function": "generate_report",
     "parameters": {
       "content": "分析结果内容"
     }
       "content": "分析结果内容"
     }
   }
     }
   }
   }
   ```
   ```
   - 这一步将根据分析结果，生成一份简要的项目可行性分析报告。      

### 注意事项：

### 注意事项：
### 注意事项：
- 请确保所有调用 `search_doc`、`analyze_data` 和 `generate_report` - 请确保所有调用 `search_doc`、`analyze_data` 和 `generate_report` 的函数调用均满足其参数要求。
- 如果搜索结果或分析结果不明确，请补充具体信息或重新调整搜索关键词 。
希望这份分析对您有所帮助！如果有进一步的问题或需要调整，请随时告诉我。


test2, siliconflow, LLM_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.antigravity\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 55551 -- d:\\shouxieagent\\exe c:\\Users\\Zac\ Liu\\.antigravity\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 55551 -- d:\\shouxieagent\\langchain\\agent.py
8.0-win32-x64\\bundled\\libs\\debugpy\\launcher 55551 -- d:\\shouxieagent\\langchain\\agent.py
langchain\\agent.py
Traceback (most recent call last):
  File "d:\shouxieagent\langchain\agent.py", line 52, in <module>
Traceback (most recent call last):
  File "d:\shouxieagent\langchain\agent.py", line 52, in <module>
  File "d:\shouxieagent\langchain\agent.py", line 52, in <module>
    result = app.invoke({
             ^^^^^^^^^^^^
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\pregel\main.py", line 3068, in invoke
    for chunk in self.stream(
  File "d:\conda_envs\shouxieagent\Lib\site-packages\langgraph\pregel\main.py", line 2671, in stream
    raise GraphRecursionError(msg)
langgraph.errors.GraphRecursionError: Recursion limit of 25 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT

test3, siliconflow, LLM_MODEL=Pro/deepseek-ai/DeepSeek-R1
--- 最终输出 ---

len(result['messages']) ==  1

根据要求，我会依次调用工具链完成拆解任务：  
1. 首先利用 `search_doc` 工具获取市场趋势、技术挑战及案例资料；
2. 调用 `analyze_data` 进行逻辑拆解与可行性评估；
3. 最后通过 `generate_report` 输出正式报告。

启动第一步信息检索工具👇

### 工具调用
```json
[
  {
    "name": "search_doc",
    "arguments": {
      "query": "AI项目市场趋势、技术挑战、落地案例及可行性分析"
    }
  }
]
```
"""


"""
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.vscode\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 62299 -- d:\\shouxieagent\\langchain\\agent_debug5_handler_callback.py 
[DEBUG] route_after_agent: stage=None, has_tool_calls=True
[DEBUG] update_stage: search_doc
[DEBUG] route_after_agent: stage=search_doc, has_tool_calls=True
[DEBUG] update_stage: analyze_data
[DEBUG] route_after_agent: stage=analyze_data, has_tool_calls=True
[DEBUG] update_stage: generate_report
[DEBUG] route_after_agent: stage=generate_report, has_tool_calls=False
"""