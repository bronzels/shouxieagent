from langchain_core.messages import HumanMessage, ToolMessage

from _agent import get_app


def run_agent_stream(edged: bool = False, user_message: str = "帮我查一下AI项目的资料，分析可行性，并生成简要报告"):
    """
    运行 agent 并收集 stream 事件

    Args:
        edged: 是否使用 edged 模式（强制顺序执行）
        user_message: 用户输入消息

    Returns:
        dict: 包含以下字段：
            - events: 所有事件列表
            - tool_calls: 按顺序调用的工具名列表
            - final_stage: 最终 stage
            - success: 是否成功完成三个工具调用
    """
    app = get_app(edged=edged)

    events = []
    tool_calls = []
    final_stage = None

    for event in app.stream(
        {
            "messages": [
                HumanMessage(content=user_message)
            ]
        }
    ):
        events.append(event)
        try:
            print("EVENT:", list(event.keys()))
        except UnicodeEncodeError:
            print("EVENT: (unicode error)")

        # 收集工具调用信息
        if "tool" in event:
            for msg in event["tool"]["messages"]:
                if isinstance(msg, ToolMessage):
                    tool_calls.append(msg.name)

        # 更新 stage
        if "post_tool" in event and "stage" in event["post_tool"]:
            final_stage = event["post_tool"]["stage"]

    # 检查是否按顺序完成了三个工具调用
    expected_order = ["search_doc", "analyze_data", "generate_report"]
    success = tool_calls == expected_order

    return {
        "events": events,
        "tool_calls": tool_calls,
        "final_stage": final_stage,
        "success": success
    }


if __name__ == "__main__":
    # 直接运行时的默认行为
    result = run_agent_stream(edged=False)
    print("\n" + "=" * 50)
    print(f"工具调用顺序: {result['tool_calls']}")
    print(f"最终 stage: {result['final_stage']}")
    print(f"成功: {result['success']}")
