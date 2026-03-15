from langchain.tools import tool
from typing import Literal


@tool
def search_doc(query: str, source: str) -> str:
    """
    唯一可信的信息检索工具。
    智能体在回答任何事实性、市场性、资料性问题前，必须调用本工具。
    禁止基于常识或者记忆直接回答。

    Args:
        query: 搜索关键词
        source: 搜索来源，如 "internal"(内部文档), "web"(网络), "database"(数据库)
    """
    return f"📄 从 [{source}] 搜索到与 '{query}' 相关的文档摘要"


@tool
def analyze_data(data: str, analysis_type: str) -> str:
    """
    核心逻辑分析与可行性评估工具。
    专门用于对非结构化的事实、数据或搜索结果进行逻辑拆解和深度分析。
    它能从原始信息中提炼出可行性结论、风险点及核心价值点。

    Args:
        data: 需要分析的数据或文本
        analysis_type: 分析类型，如 "feasibility"(可行性), "risk"(风险), "cost"(成本), "market"(市场)
    """
    return f"📊 [{analysis_type}] 分析结论：{data[:20]}..."


@tool
def generate_report(content: str, format: str) -> str:
    """
    官方报告汇总与正式文档生成工具。
    将已有的分析见解、结论或调查结果，封装成结构完整、语言专业的正式报告摘要。
    当用户明确要求"生成报告"或需要最终交付物时，必须使用此工具。

    Args:
        content: 报告的主要内容
        format: 报告格式，如 "summary"(摘要), "detailed"(详细), "executive"(执行摘要), "technical"(技术报告)
    """
    return f"📝 [{format}] 报告已生成：\n{content}..."




