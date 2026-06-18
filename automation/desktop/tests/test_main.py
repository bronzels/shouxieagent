# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from automation.desktop import kugou_vip


def test_build_task_wires_add_hours():
    from automation.desktop.config import parse_args
    args = parse_args(["--add-hours", "10", "--dry-run"])
    with patch("automation.desktop.kugou_vip.UITarsAgent"), \
         patch("automation.desktop.kugou_vip.ScrcpyWindow"), \
         patch("automation.desktop.kugou_vip.DesktopInput"):
        task = kugou_vip.build_task(args)
        assert task.add_hours == 10


def test_main_returns_zero_on_done():
    with patch("automation.desktop.kugou_vip.build_task") as bt:
        fake = MagicMock()
        fake.run.return_value = {"status": "done", "rounds": 12}
        bt.return_value = fake
        assert kugou_vip.main(["--add-hours", "14"]) == 0


def test_main_returns_nonzero_on_failed():
    with patch("automation.desktop.kugou_vip.build_task") as bt:
        fake = MagicMock()
        fake.run.return_value = {"status": "failed", "rounds": 3}
        bt.return_value = fake
        assert kugou_vip.main([]) == 1
