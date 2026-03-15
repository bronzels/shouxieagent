"""
LangGraph Plan-and-Execute Agent

基于 LangGraph 官方文档的 planner-executor 模式实现。
这种模式将任务分解为：
1. Planner Node: 生成步骤计划
2. Executor Node: 逐步执行任务
3. Replan Node: 根据执行结果更新计划
4. Conditional Edge: 检查计划是否完成

参考: https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/
"""

from typing import TypedDict, List, Annotated, Optional, Union
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

from tool import search_doc, analyze_data, generate_report
from llm import get_chat_openai


# ============ Pydantic Models for Structured Output ============

class PlanStep(BaseModel):
    """单个计划步骤"""
    step: str = Field(description="要执行的具体步骤描述")
    tool: Optional[str] = Field(default=None, description="需要调用的工具名称: search_doc, analyze_data, generate_report")


class Plan(BaseModel):
    """完整的执行计划"""
    steps: List[PlanStep] = Field(description="按顺序执行的步骤列表")


class ReplanResponse(BaseModel):
    """重新规划的响应"""
    action: Union[Plan, str] = Field(
        description="如果需要继续执行，返回更新后的 Plan；如果已完成，返回最终响应字符串"
    )


# ============ State Definition ============

class PlanExecuteState(TypedDict):
    """Plan-and-Execute Agent 的状态"""
    messages: Annotated[List, add_messages]  # 消息历史
    plan: List[str]  # 当前计划步骤列表
    current_step: int  # 当前执行到第几步
    past_steps: List[tuple]  # 已执行的步骤及其结果 [(step, result), ...]
    response: Optional[str]  # 最终响应


# ============ Prompts ============

PLANNER_PROMPT = """你是一个任务规划专家。根据用户的请求，制定一个清晰的执行计划。

可用的工具:
1. search_doc - 搜索文档资料
2. analyze_data - 分析数据并得出结论
3. generate_report - 生成正式报告

请将用户请求分解为具体的步骤，每个步骤应该:
- 明确说明要做什么
- 指定需要调用的工具（如果需要）
- 步骤之间有逻辑顺序

以 JSON 格式输出计划，包含 steps 数组，每个 step 有 step (描述) 和 tool (工具名) 字段。
"""

EXECUTOR_PROMPT = """你是一个任务执行器。执行给定的步骤并调用相应的工具。

当前步骤: {current_step}

请调用指定的工具来完成这个步骤。
"""

REPLAN_PROMPT = """你是一个任务重新规划专家。根据已执行的步骤和结果，决定下一步行动。

原始请求: {input}

已执行的步骤:
{past_steps}

如果任务已完成，请直接给出最终回复。
如果还需要继续执行，请更新剩余的计划步骤。
"""


# ============ Node Functions ============

def get_planner_app():
    """创建 Plan-and-Execute Agent"""

    tools = [search_doc, analyze_data, generate_report]
    tool_node = ToolNode(tools)
    llm = get_chat_openai()
    llm_with_tools = llm.bind_tools(tools)

    def plan_step(state: PlanExecuteState):
        """Planner 节点: 生成执行计划"""
        messages = state["messages"]
        user_input = ""
        for m in messages:
            if isinstance(m, HumanMessage):
                user_input = m.content
                break

        plan_messages = [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=f"请为以下请求制定执行计划:\n{user_input}")
        ]

        # 使用结构化输出
        try:
            structured_llm = llm.with_structured_output(Plan)
            plan_response = structured_llm.invoke(plan_messages)
            steps = [f"{s.step} [工具: {s.tool}]" if s.tool else s.step for s in plan_response.steps]
        except Exception as e:
            # 如果结构化输出失败，使用默认计划
            print(f"[DEBUG] 结构化输出失败，使用默认计划: {e}")
            steps = [
                "搜索相关文档资料 [工具: search_doc]",
                "分析搜索结果 [工具: analyze_data]",
                "生成报告 [工具: generate_report]"
            ]

        print(f"[DEBUG] plan_step: 生成计划 {steps}")
        return {
            "plan": steps,
            "current_step": 0,
            "past_steps": []
        }

    def execute_step(state: PlanExecuteState):
        """Executor 节点: 执行当前步骤"""
        plan = state["plan"]
        current_step = state.get("current_step", 0)

        if current_step >= len(plan):
            print("[DEBUG] execute_step: 所有步骤已完成")
            return {}

        step_description = plan[current_step]
        print(f"[DEBUG] execute_step: 执行步骤 {current_step + 1}/{len(plan)}: {step_description}")

        # 确定要调用的工具
        tool_name = None
        if "search_doc" in step_description:
            tool_name = "search_doc"
        elif "analyze_data" in step_description:
            tool_name = "analyze_data"
        elif "generate_report" in step_description:
            tool_name = "generate_report"

        if tool_name:
            # 强制调用指定工具
            llm_forced = get_chat_openai().bind_tools(
                tools,
                tool_choice={"type": "function", "function": {"name": tool_name}}
            )
        else:
            llm_forced = llm_with_tools

        # 构建执行消息
        exec_messages = state["messages"] + [
            SystemMessage(content=EXECUTOR_PROMPT.format(current_step=step_description))
        ]

        response = llm_forced.invoke(exec_messages)
        return {"messages": [response]}

    def process_tool_result(state: PlanExecuteState):
        """处理工具执行结果并更新状态"""
        messages = state["messages"]
        plan = state["plan"]
        current_step = state.get("current_step", 0)
        past_steps = state.get("past_steps", [])

        # 获取最后的工具执行结果
        tool_result = ""
        for m in reversed(messages):
            if hasattr(m, 'content') and hasattr(m, 'name'):
                tool_result = m.content
                break

        if current_step < len(plan):
            step_description = plan[current_step]
            past_steps = past_steps + [(step_description, tool_result)]
            print(f"[DEBUG] process_tool_result: 步骤 {current_step + 1} 完成")

        return {
            "current_step": current_step + 1,
            "past_steps": past_steps
        }

    def replan_step(state: PlanExecuteState):
        """Replan 节点: 根据执行结果决定下一步"""
        plan = state["plan"]
        current_step = state.get("current_step", 0)
        past_steps = state.get("past_steps", [])

        print(f"[DEBUG] replan_step: current_step={current_step}, plan_length={len(plan)}")

        # 如果所有步骤都执行完了
        if current_step >= len(plan):
            # 收集所有结果生成最终响应
            results = "\n".join([f"- {step}: {result}" for step, result in past_steps])
            response = f"任务已完成！\n\n执行结果:\n{results}"
            print(f"[DEBUG] replan_step: 任务完成")
            return {"response": response}

        # 还有步骤需要执行
        print(f"[DEBUG] replan_step: 继续执行下一步")
        return {}

    def should_continue(state: PlanExecuteState):
        """决定是否继续执行"""
        response = state.get("response")
        if response:
            print("[DEBUG] should_continue: 任务完成，结束")
            return "end"

        # 检查最后的消息是否有 tool_calls
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                print("[DEBUG] should_continue: 有 tool_calls，执行工具")
                return "execute_tool"

        print("[DEBUG] should_continue: 继续执行")
        return "continue"

    def route_after_executor(state: PlanExecuteState):
        """executor 之后的路由"""
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                return "tool"
        return "replan"

    # ============ Build Graph ============

    graph = StateGraph(PlanExecuteState)

    # 添加节点
    graph.add_node("planner", plan_step)
    graph.add_node("executor", execute_step)
    graph.add_node("tool", tool_node)
    graph.add_node("process_result", process_tool_result)
    graph.add_node("replan", replan_step)

    # 添加边
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")

    # executor 之后根据是否有 tool_calls 决定
    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {"tool": "tool", "replan": "replan"}
    )

    # tool 执行后处理结果
    graph.add_edge("tool", "process_result")
    graph.add_edge("process_result", "replan")

    # replan 之后决定是继续还是结束
    graph.add_conditional_edges(
        "replan",
        should_continue,
        {"continue": "executor", "execute_tool": "tool", "end": END}
    )

    return graph.compile()


def run_planned_agent(user_message: str = "帮我查一下AI项目的资料，分析可行性，并生成简要报告"):
    """
    运行 Plan-and-Execute Agent

    Args:
        user_message: 用户输入消息

    Returns:
        dict: 包含执行结果的字典
    """
    app = get_planner_app()

    events = []
    tool_calls = []
    final_response = None

    print(f"\n{'='*60}")
    print(f"用户请求: {user_message}")
    print(f"{'='*60}\n")

    for event in app.stream(
        {
            "messages": [HumanMessage(content=user_message)]
        }
    ):
        events.append(event)
        print(f"EVENT: {list(event.keys())}")

        # 收集工具调用
        if "tool" in event:
            for msg in event["tool"].get("messages", []):
                if hasattr(msg, 'name'):
                    tool_calls.append(msg.name)
                    print(f"  -> 工具调用: {msg.name}")

        # 获取最终响应
        if "replan" in event and event["replan"] and event["replan"].get("response"):
            final_response = event["replan"]["response"]

    print(f"\n{'='*60}")
    print(f"Tool calls: {tool_calls}")
    print(f"{'='*60}")

    if final_response:
        try:
            print(f"\nFinal response:\n{final_response}")
        except UnicodeEncodeError:
            print(f"\nFinal response: (contains special characters, check success flag)")

    expected_order = ["search_doc", "analyze_data", "generate_report"]
    success = tool_calls == expected_order

    return {
        "events": events,
        "tool_calls": tool_calls,
        "response": final_response,
        "success": success
    }


if __name__ == "__main__":
    result = run_planned_agent()
    print(f"\n{'#'*60}")
    print(f"测试结果: {'PASS' if result['success'] else 'FAIL'}")
    print(f"{'#'*60}")
