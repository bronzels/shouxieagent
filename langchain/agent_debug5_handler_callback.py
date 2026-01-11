from langchain_core.messages import HumanMessage
from langchain_core.callbacks import StdOutCallbackHandler

from _agent import get_app

app = get_app()

handler = StdOutCallbackHandler()
result = app.invoke(
    {
        "messages": [
            HumanMessage(content="帮我查一下AI项目的资料，分析一下可行性，然后生成一份简要报告")
        ]
    },
    callbacks={
        "callbacks": [handler]
    }
)

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

