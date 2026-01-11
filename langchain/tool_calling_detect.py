from langchain.tools import tool

from llm import get_chat_openai

@tool
def ping(x: int) -> int:
    """Return x + 1"""
    return x + 1

llm = get_chat_openai().bind_tools([ping])

def supports_tool_calling(llm):
    from langchain_core.messages import HumanMessage
    try:
        msg = llm.bind_tools([ping]).invoke([
            HumanMessage(content="请调用 ping 工具，参数 x=1")
        ])
        return bool(msg.tool_calls)
    except Exception:
        return False

if not supports_tool_calling(llm):
    raise RuntimeError("This model does NOT support tool calling")
print("This model supports tool calling")