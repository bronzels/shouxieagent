from langchain_core.messages import HumanMessage
from langchain_core.callbacks import StdOutCallbackHandler

from _agent import get_app

app = get_app()

handler = StdOutCallbackHandler()
for event in app.stream(
    {"messages": [
        HumanMessage(content="做AI项目搜索调研并输出报告")
        ]},
    config={"callbacks": [handler]}
):
    pass

"""
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.vscode\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 61391 -- d:\\shouxieagent\\langchain\\agent_debug4_stream_handler_callback.py


> Entering new LangGraph chain...


> Entering new agent chain...


> Entering new route_after_agent chain...
[DEBUG] route_after_agent: stage=None, has_tool_calls=True

> Finished chain.

> Finished chain.


> Entering new tool chain...
content='📄 搜索到与 AI项目 人工智能项目 市场调研 发展趋势 应用场景 相关的文档摘要' name='search_doc' tool_call_id='toolu_bdrk_012uq5kGq3CaNRzDf5tRyFFG'
> Finished chain.


> Entering new post_tool chain...
[DEBUG] update_stage: search_doc

> Finished chain.


> Entering new agent chain...


> Entering new route_after_agent chain...
[DEBUG] route_after_agent: stage=search_doc, has_tool_calls=True

> Finished chain.

> Finished chain.


> Entering new tool chain...
content='📊 对数据进行分析，结论是：AI项目调研搜索结果：📄 搜索到与 AI...' name='analyze_data' tool_call_id='toolu_bdrk_013mgirevoRvU9S7i7Ex2aq5'
> Finished chain.


> Entering new post_tool chain...
[DEBUG] update_stage: analyze_data

> Finished chain.


> Entering new agent chain...


> Entering new route_after_agent chain...
[DEBUG] route_after_agent: stage=analyze_data, has_tool_calls=True

> Finished chain.

> Finished chain.


> Entering new tool chain...
content='📝 报告已生成：\nAI项目搜索调研分析报告内容：基于搜索到的AI项目相关文档摘要及深度分析结果，生成关于AI项目市场调研、发展趋势、应用场景、可行性结论、风险点及核心价值点的正式报告。...' name='generate_report' tool_call_id='toolu_bdrk_01GEiBCLxrr1p1a34fLfBudw'
> Finished chain.


> Entering new post_tool chain...
[DEBUG] update_stage: generate_report

> Finished chain.


> Entering new agent chain...


> Entering new route_after_agent chain...
[DEBUG] route_after_agent: stage=generate_report, has_tool_calls=False

> Finished chain.

> Finished chain.

> Finished chain.
"""