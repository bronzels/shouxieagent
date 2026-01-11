from langchain_core.messages import HumanMessage
from langchain_core.messages import AIMessage

from _agent import get_app

app = get_app()

for event in app.stream(
    {
        "messages": [
            HumanMessage(content="搜索AI项目资料，分析并写报告")
        ]
    }
):
    for _, output in event.items():
        for msg in output.get("messages", []):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for call in msg.tool_calls:
                    print(f"[CALL] {call['name']}")
                    print(f"  args: {call['args']}")

"""
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.vscode\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 50593 -- d:\\shouxieagent\\langchain\\agent_debug3_stream_call_arg.py
[DEBUG] route_after_agent: stage=None, has_tool_calls=True
[CALL] search_doc
  args: {'query': 'AI项目资料'}
[DEBUG] update_stage: search_doc
[DEBUG] route_after_agent: stage=search_doc, has_tool_calls=True
[CALL] analyze_data
  args: {'data': '搜索到与 AI项目资料 相关的文档摘要'}
[DEBUG] update_stage: analyze_data
[DEBUG] route_after_agent: stage=analyze_data, has_tool_calls=True
[CALL] generate_report
  args: {'content': '基于AI项目资料的搜索结果和分析结论，生成正式报告。搜索结果：搜索到与 AI项目资料 相关 的文档摘要。分析结论：对数据进行分析，结论是：搜索到与 AI项目资料 相关的文档摘要...'}
[DEBUG] update_stage: generate_report
[DEBUG] route_after_agent: stage=generate_report, has_tool_calls=False
"""