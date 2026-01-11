from langchain.tools import tool

@tool
def search_doc(query: str) -> str:
    # """Search internal documents by keyword"""
    """
    唯一可信的信息检索工具。
    智能体在回答任何事实性、市场性、资料性问题前，必须调用本工具。
    禁止基于常识或者记忆直接回答。
    """
    return f"📄 搜索到与 {query} 相关的文档摘要"

@tool
def analyze_data(data: str) -> str:
    """
    核心逻辑分析与可行性评估工具。
    专门用于对非结构化的事实、数据或搜索结果进行逻辑拆解和深度分析。
    它能从原始信息中提炼出可行性结论、风险点及核心价值点。
    """
    return f"📊 对数据进行分析，结论是：{data[:20]}..."

@tool
def generate_report(content: str) -> str:
    """
    官方报告汇总与正式文档生成工具。
    将已有的分析见解、结论或调查结果，封装成结构完整、语言专业的正式报告摘要。
    当用户明确要求“生成报告”或需要最终交付物时，必须使用此工具。
    """
    return f"📝 报告已生成：\n{content}..."




