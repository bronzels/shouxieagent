# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
from PIL import Image
from automation.desktop.task_kugou import KugouTask


def _mock_window():
    w = MagicMock()
    w.grab.return_value = (Image.new("RGB", (100, 100)), (0, 0, 100, 100))
    return w


def test_run_done_when_agent_signals_finished():
    win = _mock_window()
    agent = MagicMock()
    # 第一步就返回 finished → 状态机应判定 done
    agent.step.return_value = {"type": "finished"}
    inp = MagicMock()
    task = KugouTask(win, agent, inp, target_hours=14, max_rounds=5)
    result = task.run()
    assert result["status"] in ("done", "limit")


def test_run_failed_when_agent_returns_none_repeatedly():
    win = _mock_window()
    agent = MagicMock()
    agent.step.return_value = None  # 一直解析失败
    inp = MagicMock()
    task = KugouTask(win, agent, inp, max_rounds=5)
    result = task.run()
    assert result["status"] == "failed"


def test_run_hits_max_rounds():
    win = _mock_window()
    agent = MagicMock()
    # 一直返回普通 click，永不 finished
    agent.step.return_value = {"type": "click", "x": 50, "y": 50}
    inp = MagicMock()
    task = KugouTask(win, agent, inp, max_rounds=3)
    result = task.run()
    assert result["status"] == "max_rounds"
    assert result["rounds"] == 3


def test_each_round_activates_and_grabs():
    win = _mock_window()
    agent = MagicMock()
    agent.step.return_value = {"type": "finished"}
    inp = MagicMock()
    KugouTask(win, agent, inp, max_rounds=5).run()
    assert win.activate.called and win.grab.called
