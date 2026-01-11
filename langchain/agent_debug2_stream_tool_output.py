from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage

from _agent import get_app

app = get_app()

for event in app.stream(
    {
        "messages": [
            HumanMessage(content="主题：AI项目，步骤：查资料→分析→报告")
        ]
    }
):
    for node, output in event.items():
        msgs = output.get("messages", [])
        for m in msgs:
            if isinstance(m, ToolMessage):
                print(f"[TOOL] {m.name}")
                print(f"  output: {m.content}")
"""
HumanMessage(content="查资料→分析→报告")
好的，我理解您希望完成一个完整的流程：**查资料 → 分析 → 报告**。\n\n但我需要您提供具体的信息才能开始：\n\n**请告诉我：您想查询什么主题/问题？**\n\n例如：\n- 某个 行业的市场分析\n- 某家公司的经营情况\n- 某项技术的发展趋势\n- 某个政策的影响评估\n- 其他您关心的具体问题\n\n请提供具体的查询需求，我将按照流程为您完成。

HumanMessage(content="主题：AI项目，步骤：查资料→分析→报告")
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.vscode\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 63312 -- d:\\shouxieagent\\langchain\\agent_debug2_stream_tool_output.py
[DEBUG] route_after_agent: stage=None, has_tool_calls=True
[TOOL] search_doc
  output: 📄 搜索到与 AI项目 人工智能项目 发展趋势 应用场景 市场分析 相关的文档摘要
[DEBUG] update_stage: search_doc
[DEBUG] route_after_agent: stage=search_doc, has_tool_calls=True
[TOOL] search_doc
  output: 📄 搜索到与 AI项目 人工智能项目 发展趋势 应用场景 市场分析 相关的文档摘要
[DEBUG] update_stage: search_doc
[DEBUG] route_after_agent: stage=search_doc, has_tool_calls=True
[TOOL] analyze_data
  output: 📊 对数据进行分析，结论是：AI项目相关资料：人工智能项目发展趋势、...
[DEBUG] update_stage: analyze_data
[DEBUG] route_after_agent: stage=analyze_data, has_tool_calls=True
[TOOL] generate_report
  output: 📝 报告已生成：
主题：AI项目分析报告。基于检索的AI项目发展趋势、应用场景、市场分析资料，以及对可行性、核心价值点、潜在风险和市场机会的深度分析，生成正式的AI项目综合分析报告。...
[DEBUG] update_stage: generate_report
[DEBUG] route_after_agent: stage=generate_report, has_tool_calls=False
"""