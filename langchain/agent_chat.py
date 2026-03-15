"""
Multi-turn Chat Agent with Parameter Collection

基于 _agent.py 扩展的多轮对话程序。
特点：
1. 支持 stdio 输入的多轮对话
2. 当工具缺少必要参数时，会追问用户收集信息
3. 保持完整的对话历史

用法：
    python agent_chat.py
"""

from langchain_core.messages import AIMessage, ToolMessage, BaseMessage
from langchain_core.messages import SystemMessage, HumanMessage
from tool import search_doc, analyze_data, generate_report
from llm import get_chat_openai

from typing import TypedDict, List, Annotated, Optional
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


SYSTEM_PROMPT = SystemMessage(content="""你是一个智能助手，可以帮助用户搜索资料、分析数据和生成报告。

可用工具：
1. search_doc(query, source) - 搜索文档
   - query: 搜索关键词
   - source: 搜索来源 (internal/web/database)

2. analyze_data(data, analysis_type) - 分析数据
   - data: 要分析的数据
   - analysis_type: 分析类型 (feasibility/risk/cost/market)

3. generate_report(content, format) - 生成报告
   - content: 报告内容
   - format: 报告格式 (summary/detailed/executive/technical)

重要规则：
1. 调用工具前，必须确保所有必需参数都已获得
2. 如果用户没有提供某个必需参数，请直接询问用户，不要猜测
3. 用简洁友好的方式向用户追问缺失的信息
4. 每次只执行一个工具调用，确保参数完整

追问示例：
- "请问您希望从哪个来源搜索？(internal/web/database)"
- "您需要进行哪种类型的分析？(可行性/风险/成本/市场)"
- "报告需要什么格式？(摘要/详细/执行摘要/技术报告)"
""")


class ChatState(TypedDict):
    """多轮对话的状态"""
    messages: Annotated[List, add_messages]  # 消息历史（累积）
    pending_tool: Optional[str]  # 待执行的工具（如果有）
    missing_params: Optional[List[str]]  # 缺失的参数列表


def create_chat_agent():
    """创建多轮对话 Agent"""

    tools = [search_doc, analyze_data, generate_report]
    llm = get_chat_openai().bind_tools(tools)
    tool_node = ToolNode(tools)

    def agent_node(state: ChatState):
        """Agent 决策节点"""
        messages = state["messages"]

        # 确保系统提示在最前面
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SYSTEM_PROMPT] + list(messages)

        response = llm.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: ChatState):
        """决定下一步：执行工具、询问用户还是结束"""
        messages = state["messages"]
        last_message = messages[-1]

        # 如果最后一条消息有 tool_calls，执行工具
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tool"

        # 否则等待用户输入
        return "wait_user"

    # 构建图
    graph = StateGraph(ChatState)

    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tool": "tool",
            "wait_user": END
        }
    )

    # 工具执行后返回 agent 继续处理
    graph.add_edge("tool", "agent")

    return graph.compile()


def run_chat():
    """运行多轮对话"""
    app = create_chat_agent()

    # 对话状态
    state = {"messages": [], "pending_tool": None, "missing_params": None}

    print("=" * 60)
    print("Multi-turn Chat Agent")
    print("=" * 60)
    print("Tips:")
    print("  - Type your message and press Enter")
    print("  - Type 'quit' or 'exit' to end")
    print("  - Type 'clear' to start a new conversation")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break

        if user_input.lower() == 'clear':
            state = {"messages": [], "pending_tool": None, "missing_params": None}
            print("[Conversation cleared]\n")
            continue

        # 添加用户消息
        state["messages"].append(HumanMessage(content=user_input))

        # 运行 agent
        try:
            print("\nAgent: ", end="", flush=True)

            # 使用 stream 来获取逐步输出
            final_response = ""
            tool_calls_made = []

            for event in app.stream(state):
                # 处理 agent 输出
                if "agent" in event:
                    agent_messages = event["agent"].get("messages", [])
                    for msg in agent_messages:
                        if isinstance(msg, AIMessage):
                            if msg.content:
                                final_response = msg.content
                            if msg.tool_calls:
                                for tc in msg.tool_calls:
                                    tool_calls_made.append(tc["name"])
                                    print(f"[Calling {tc['name']}...]", end=" ", flush=True)

                # 处理工具输出
                if "tool" in event:
                    tool_messages = event["tool"].get("messages", [])
                    for msg in tool_messages:
                        if isinstance(msg, ToolMessage):
                            print(f"[Done]", end=" ", flush=True)

            # 打印最终响应
            if final_response:
                print(final_response)
            else:
                print("(No text response)")

            # 更新状态（获取完整的消息历史）
            # 从最后的 event 中获取累积的消息
            for event in app.stream({"messages": state["messages"]}):
                pass  # 重新运行以获取最终状态

            # 简单方式：直接用 invoke 获取最终状态
            final_state = app.invoke({"messages": state["messages"]})
            state["messages"] = final_state["messages"]

        except Exception as e:
            print(f"\n[Error: {e}]")
            import traceback
            traceback.print_exc()

        print()


def run_chat_simple():
    """简化版多轮对话（不使用 stream）"""
    app = create_chat_agent()

    messages = []

    print("=" * 60)
    print("Multi-turn Chat Agent (Simple Mode)")
    print("=" * 60)
    print("Commands: 'quit'=exit, 'clear'=new conversation")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break

        if user_input.lower() == 'clear':
            messages = []
            print("[Conversation cleared]\n")
            continue

        # 添加用户消息
        messages.append(HumanMessage(content=user_input))

        try:
            # 运行 agent
            result = app.invoke({"messages": messages})

            # 更新消息历史
            messages = result["messages"]

            # 打印 agent 响应
            print("\nAgent: ", end="")

            # 找到最后的 AI 响应
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    if msg.content:
                        print(msg.content)
                    elif msg.tool_calls:
                        print(f"[Called tools: {[tc['name'] for tc in msg.tool_calls]}]")
                    break

            # 打印工具结果（如果有）
            for msg in messages:
                if isinstance(msg, ToolMessage):
                    try:
                        print(f"  [{msg.name}]: {msg.content[:100]}...")
                    except UnicodeEncodeError:
                        print(f"  [{msg.name}]: (result contains special chars)")

        except Exception as e:
            print(f"\n[Error: {e}]")
            import traceback
            traceback.print_exc()

        print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--simple":
        run_chat_simple()
    else:
        run_chat_simple()  # 默认使用简化版，更稳定
