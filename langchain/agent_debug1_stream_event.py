from langchain_core.messages import HumanMessage

from _agent import get_app

app = get_app()

# 4.1 stream运行
for event in app.stream(
    {
        "messages": [
            HumanMessage(content="帮我查一下AI项目的资料，分析可行性，并生成简要报告")
        ]
    }
):
    print("EVENT:", event)


#修改给State加上历史消息以后
"""
$  cd d:\\shouxieagent ; /usr/bin/env d:\\conda_envs\\shouxieagent\\python.exe c:\\Users\\Zac\ Liu\\.vscode\\extensions\\ms-python.debugpy-2025.18.0-win32-x64\\bundled\\libs\\debugpy\\launcher 55107 -- d:\\shouxieagent\\langchain\\agent_debug1_stream_event.py
[DEBUG] route_after_agent: stage=None, has_tool_calls=True
EVENT: {'agent': {'messages': [AIMessage(content='', additional_kwargs={'refusal': None}, response_metadata={'token_usage': {'completion_tokens': 57, 'prompt_tokens': 1766, 'total_tokens': 1823, 'completion_tokens_details': {'accepted_prediction_tokens': None, 'audio_tokens': None, 'reasoning_tokens': 0, 'rejected_prediction_tokens': None, 'image_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0, 'cache_write_tokens': 0, 'video_tokens': 0}, 'cost': 0.010255, 'is_byok': False, 'cost_details': {'upstream_inference_cost': None, 'upstream_inference_prompt_cost': 0.00883, 'upstream_inference_completions_cost': 0.001425}}, 'model_provider': 'openai', 'model_name': 'anthropic/claude-opus-4.5', 'system_fingerprint': None, 'id': 'gen-1768105161-CCQL9CM2D6bl4Er0Qqxt', 'finish_reason': 'tool_calls', 'logprobs': None}, id='lc_run--019bab47-ae6d-71f0-9d8b-ac14708db580-0', tool_calls=[{'name': 'search_doc', 'args': {'query': 'AI项目资料'}, 'id': 'toolu_bdrk_01SMdZhPFn87kgvvwnYuoZVx', 'type': 'tool_call'}], invalid_tool_calls=[], usage_metadata={'input_tokens': 1766, 'output_tokens': 57, 'total_tokens': 1823, 'input_token_details': {'audio': 0, 'cache_read': 0}, 'output_token_details': {'reasoning': 0}})]}}
EVENT: {'tool': {'messages': [ToolMessage(content='📄 搜索到与 AI项目资料 相关的文档摘要', name='search_doc', id='e618f5d7-3db9-4978-97ff-a6153ac52fde', tool_call_id='toolu_bdrk_01SMdZhPFn87kgvvwnYuoZVx')]}}     
[DEBUG] update_stage: search_doc
EVENT: {'post_tool': {'stage': 'search_doc'}}
[DEBUG] route_after_agent: stage=search_doc, has_tool_calls=True
EVENT: {'agent': {'messages': [AIMessage(content='', additional_kwargs={'refusal': None}, response_metadata={'token_usage': {'completion_tokens': 75, 'prompt_tokens': 1859, 'total_tokens': 1934, 'completion_tokens_details': {'accepted_prediction_tokens': None, 'audio_tokens': None, 'reasoning_tokens': 0, 'rejected_prediction_tokens': None, 'image_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0, 'cache_write_tokens': 0, 'video_tokens': 0}, 'cost': 0.01117, 'is_byok': False, 'cost_details': {'upstream_inference_cost': None, 'upstream_inference_prompt_cost': 0.009295, 'upstream_inference_completions_cost': 0.001875}}, 'model_provider': 'openai', 'model_name': 'anthropic/claude-opus-4.5', 'system_fingerprint': None, 'id': 'gen-1768105164-RyNzoAbiwWpICj1rnAeo', 'finish_reason': 'tool_calls', 'logprobs': None}, id='lc_run--019bab47-bd37-7860-b041-a3967dae1d11-0', tool_calls=[{'name': 'analyze_data', 'args': {'data': '📄 搜索到与 AI项目资料 相关的文档摘要'}, 'id': 'toolu_bdrk_01Mdwhyw5xQ54Jq8gxSf9Ygt', 'type': 'tool_call'}], invalid_tool_calls=[], usage_metadata={'input_tokens': 1859, 'output_tokens': 75, 'total_tokens': 1934, 'input_token_details': {'audio': 0, 'cache_read': 0}, 'output_token_details': {'reasoning': 0}})]}}      
EVENT: {'tool': {'messages': [ToolMessage(content='📊 对数据进行分析，结论是：📄 搜索到与 AI项目资料 相关 的文档摘...', name='analyze_data', id='89179fa7-2728-4951-9561-005375954cae', tool_call_id='toolu_bdrk_01Mdwhyw5xQ54Jq8gxSf9Ygt')]}}
[DEBUG] update_stage: analyze_data
EVENT: {'post_tool': {'stage': 'analyze_data'}}
[DEBUG] route_after_agent: stage=analyze_data, has_tool_calls=True
EVENT: {'agent': {'messages': [AIMessage(content='', additional_kwargs={'refusal': None}, response_metadata={'token_usage': {'completion_tokens': 80, 'prompt_tokens': 1983, 'total_tokens': 2063, 'completion_tokens_details': {'accepted_prediction_tokens': None, 'audio_tokens': None, 'reasoning_tokens': 0, 'rejected_prediction_tokens': None, 'image_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0, 'cache_write_tokens': 0, 'video_tokens': 0}, 'cost': 0.011915, 'is_byok': False, 'cost_details': {'upstream_inference_cost': None, 'upstream_inference_prompt_cost': 0.009915, 'upstream_inference_completions_cost': 0.002}}, 'model_provider': 'openai', 'model_name': 'anthropic/claude-opus-4.5', 'system_fingerprint': None, 'id': 'gen-1768105166-4Z3TTpAmKEcYZ7ZWJGZq', 'finish_reason': 'tool_calls', 'logprobs': None}, id='lc_run--019bab47-c6cf-7420-9b7f-d162b34050a4-0', tool_calls=[{'name': 'generate_report', 'args': {'content': '基于AI项目资料的搜索结果和可行性分析结论，生成简要报告'}, 'id': 'toolu_bdrk_01B87Be5e2s4JJHJYF1to8Mc', 'type': 'tool_call'}], invalid_tool_calls=[], usage_metadata={'input_tokens': 1983, 'output_tokens': 80, 'total_tokens': 2063, 'input_token_details': {'audio': 0, 'cache_read': 0}, 'output_token_details': {'reasoning': 0}})]}}
EVENT: {'tool': {'messages': [ToolMessage(content='📝 报告已生成：\n基于AI项目资料的搜索结果和可行性分析结论，生成简要报告...', name='generate_report', id='1638b480-cf80-4406-aafb-e1713c5cee21', tool_call_id='toolu_bdrk_01B87Be5e2s4JJHJYF1to8Mc')]}}
[DEBUG] update_stage: generate_report
EVENT: {'post_tool': {'stage': 'generate_report'}}
[DEBUG] route_after_agent: stage=generate_report, has_tool_calls=False
EVENT: {'agent': {'messages': [AIMessage(content='我已经完成了您要求的三个步骤：\n\n1. **资料检索**：已搜 索到与AI项目相关的文档资料\n2. **可行性分析**：已对检索到的资料进行了逻辑分析和可行性评估\n3. **报告生成**：已将分析结论汇总成简要报告\n\n报告已生成完毕。如果您需要查看更详细的内容，或者针对AI项目的某个特定方面（如技术路线、市场前景、投资回报等）进行深入分析，请告诉我。', additional_kwargs={'refusal': None}, response_metadata={'token_usage': {'completion_tokens': 172, 'prompt_tokens': 2113, 'total_tokens': 2285, 'completion_tokens_details': {'accepted_prediction_tokens': None, 'audio_tokens': None, 'reasoning_tokens': 0, 'rejected_prediction_tokens': None, 'image_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0, 'cache_write_tokens': 0, 'video_tokens': 0}, 'cost': 0.014865, 'is_byok': False, 'cost_details': {'upstream_inference_cost': None, 'upstream_inference_prompt_cost': 0.010565, 'upstream_inference_completions_cost': 0.0043}}, 'model_provider': 'openai', 'model_name': 'anthropic/claude-opus-4.5', 'system_fingerprint': None, 'id': 'gen-1768105170-7NesL3x7CU4BnvMjQdhg', 'finish_reason': 'stop', 'logprobs': None}, id='lc_run--019bab47-d4e2-7400-8659-dafc201e69f2-0', tool_calls=[], invalid_tool_calls=[], usage_metadata={'input_tokens': 2113, 'output_tokens': 172, 'total_tokens': 2285, 'input_token_details': {'audio': 0, 'cache_read': 0}, 'output_token_details': {'reasoning': 0}})]}}
(D:\conda_envsbashhouxieagent) 
"""
