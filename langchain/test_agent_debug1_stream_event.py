import pytest
from agent_debug1_stream_event import run_agent_stream


class TestAgentStreamEvent:
    """测试 agent 的工具调用顺序"""

    def test_edged_false_model_driven(self):
        """
        测试 edged=False 模式（模型自主决策）

        验证：模型能够自主按顺序调用 search_doc -> analyze_data -> generate_report
        """
        print("\n" + "=" * 60)
        print("测试 edged=False 模式（模型自主决策）")
        print("=" * 60)

        result = run_agent_stream(edged=False)

        print("\n" + "-" * 40)
        print(f"工具调用顺序: {result['tool_calls']}")
        print(f"最终 stage: {result['final_stage']}")
        print(f"成功: {result['success']}")

        # 断言
        assert result["success"], f"期望调用顺序 ['search_doc', 'analyze_data', 'generate_report']，实际: {result['tool_calls']}"
        assert result["final_stage"] == "generate_report", f"期望最终 stage 为 'generate_report'，实际: {result['final_stage']}"

    def test_edged_true_forced_order(self):
        """
        测试 edged=True 模式（强制顺序执行）

        验证：通过显式边强制按顺序执行 search_doc -> analyze_data -> generate_report
        """
        print("\n" + "=" * 60)
        print("测试 edged=True 模式（强制顺序执行）")
        print("=" * 60)

        result = run_agent_stream(edged=True)

        print("\n" + "-" * 40)
        print(f"工具调用顺序: {result['tool_calls']}")
        print(f"最终 stage: {result['final_stage']}")
        print(f"成功: {result['success']}")

        # 断言
        assert result["success"], f"期望调用顺序 ['search_doc', 'analyze_data', 'generate_report']，实际: {result['tool_calls']}"
        assert result["final_stage"] == "generate_report", f"期望最终 stage 为 'generate_report'，实际: {result['final_stage']}"


if __name__ == "__main__":
    # 直接运行测试
    test = TestAgentStreamEvent()

    print("\n" + "#" * 70)
    print("# 运行测试用例")
    print("#" * 70)

    try:
        test.test_edged_false_model_driven()
        print("\n[PASS] test_edged_false_model_driven")
    except AssertionError as e:
        print(f"\n[FAIL] test_edged_false_model_driven: {e}")

    try:
        test.test_edged_true_forced_order()
        print("\n[PASS] test_edged_true_forced_order")
    except AssertionError as e:
        print(f"\n[FAIL] test_edged_true_forced_order: {e}")
