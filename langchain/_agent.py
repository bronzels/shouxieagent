from langchain_core.messages import AIMessage
from tool import search_doc, analyze_data, generate_report
from llm import get_chat_openai

from typing import TypedDict, List, Annotated
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, BaseMessage

SYSTEM_PROMPT = SystemMessage(content="""
你是一个严格的工具驱动智能体

规则（必须遵守）：
1. 在调用必要工具之前，禁止直接用自然语言回答用户
2. 每一步只决定「是否调用哪个工具」，不要一次性规划全部流程
3. 不需要你决定是否由你生成报告
""")


def get_app(edged = False):
  tools = [
      search_doc,
      analyze_data,
      generate_report
  ]

  # 2. 获取 LLM 并绑定工具，这样模型才知道有哪些工具可用
  llm = get_chat_openai().bind_tools(tools)

  class AgentState(TypedDict):
      messages: Annotated[List, add_messages]  # 使用 add_messages 让消息累积而非覆盖
      stage: str 

  def update_stage_after_tool_call(state: AgentState):
    """更新 stage 为最后一个 ToolMessage 的工具名"""
    # 从后往前找最后一个 ToolMessage
    for m in reversed(state["messages"]):
      if isinstance(m, ToolMessage):
        print(f"[DEBUG] update_stage: {m.name}")
        return {"stage": m.name}  # 返回增量更新
    return {}

  # 定义工具执行节点
  tool_node = ToolNode(tools)

  def normalize_messages(messages):
    nomalized = []
    for m in messages:
        # 已经是LangChain Message，原样保留
        if isinstance(m, BaseMessage):
          nomalized.append(m)
          continue
        # 如果是元组，转换为LangChain Message
        if isinstance(m, tuple):
            role, content = m
            if role == "user":
              nomalized.append(HumanMessage(content=content))
            elif role == "system":
              nomalized.append(SystemMessage(content=content))
            elif role == "assistant":
              nomalized.append(AIMessage(content=content))
            else:
              raise ValueError(f"Unknown role: {role}")
            continue
        # 其他一律不接受
        raise TypeError(f"Unknown message type: {type(m)}")
    return nomalized

  # 定义智能体决策节点
  def agent_node(state: AgentState):
      messages = state["messages"]
      #messages = normalize_messages(state["messages"])
      if not any (m.type == "system" for m in messages):
        messages.insert(0, SYSTEM_PROMPT)
      # 使用绑定了工具的 llm
      return {
          "messages": [llm.invoke(messages)]
      }

  def agent_node_edged(state: AgentState):
      """
      edged 模式的 agent 节点：根据当前 stage 使用 tool_choice 强制调用下一个工具
      """
      messages = state["messages"]
      if not any(m.type == "system" for m in messages):
          messages.insert(0, SYSTEM_PROMPT)

      stage = state.get("stage")

      # 根据 stage 决定下一个要调用的工具
      if stage is None:
          # 第一步：强制调用 search_doc
          llm_forced = get_chat_openai().bind_tools(
              tools,
              tool_choice={"type": "function", "function": {"name": "search_doc"}}
          )
      elif stage == "search_doc":
          # 第二步：强制调用 analyze_data
          llm_forced = get_chat_openai().bind_tools(
              tools,
              tool_choice={"type": "function", "function": {"name": "analyze_data"}}
          )
      elif stage == "analyze_data":
          # 第三步：强制调用 generate_report
          llm_forced = get_chat_openai().bind_tools(
              tools,
              tool_choice={"type": "function", "function": {"name": "generate_report"}}
          )
      else:
          # 已完成所有工具调用，让模型自由回复
          llm_forced = get_chat_openai().bind_tools(tools, tool_choice="none")

      return {
          "messages": [llm_forced.invoke(messages)]
      }

  graph = StateGraph(AgentState)

  # 根据 edged 参数选择不同的 agent 节点
  if edged:
      graph.add_node("agent", agent_node_edged)
  else:
      graph.add_node("agent", agent_node)

  # 两种模式都使用统一的 tool_node
  # edged 模式通过 tool_choice 强制工具选择，不需要独立节点
  graph.add_node("tool", tool_node)

  # 3. 设置边逻辑
  # agent -> tool （当模型请求 tool_calls 时）

  def force_inject_generate_report(state: AgentState, last_message: AIMessage) -> bool:
      """
      强制注入 generate_report 工具调用（用于模型推理能力不足时的兜底方案）

      当模型完成 analyze_data 后没有主动调用 generate_report 时，
      可调用此函数强制注入 tool_call。

      Args:
          state: 当前 agent 状态
          last_message: 最后一条 AIMessage，会被原地修改

      Returns:
          bool: 是否成功注入
      """
      import uuid
      # 收集之前的分析结果作为报告内容
      analysis_content = ""
      for m in state["messages"]:
          if isinstance(m, ToolMessage) and m.name == "analyze_data":
              analysis_content = m.content
      # 手动注入 tool_call 到 AIMessage
      last_message.tool_calls = [{
          "name": "generate_report",
          "args": {"content": analysis_content or "AI项目可行性分析结果"},
          "id": str(uuid.uuid4()),
          "type": "tool_call"
      }]
      print(f"[DEBUG] 强制注入 generate_report tool_call")
      return True

  def route_after_agent(state: AgentState):
      last = state["messages"][-1]
      stage = state.get("stage")
      print(f"[DEBUG] route_after_agent: stage={stage}, has_tool_calls={bool(last.tool_calls)}")

      # 如果模型有 tool_calls，正常走 tool
      if last.tool_calls:
          return "tool"

      # 如果刚完成 analyze_data 但模型没有调用 generate_report，可启用强制注入
      # （当前模型能力足够，已注释掉；若换用小模型可取消注释）
      # if stage == "analyze_data":
      #     force_inject_generate_report(state, last)
      #     return "tool"

      return END

  # edged 和非 edged 模式使用相同的路由逻辑
  # edged 模式的工具强制选择已在 agent_node_edged 中通过 tool_choice 实现
  graph.add_conditional_edges(
      "agent",
      route_after_agent
  )

  # tool -> agent (工具执行完返回 agent 继续决策)
  graph.add_node("post_tool", update_stage_after_tool_call)
  graph.add_edge("tool", "post_tool")
  graph.add_edge("post_tool", "agent")

  graph.set_entry_point("agent")

  app = graph.compile()
  return app

