import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsers import (parse_duration_to_minutes, norm_to_pixel,
                     find_keyword_bounds, extract_duration_from_xml, decide_action,
                     parse_required_seconds)


def test_parse_hours_and_minutes():
    assert parse_duration_to_minutes("剩余3小时20分") == 200

def test_parse_minutes_only():
    assert parse_duration_to_minutes("免费畅听 200分钟") == 200

def test_parse_decimal_hours():
    assert parse_duration_to_minutes("VIP剩余3.5小时") == 210

def test_parse_hours_only():
    assert parse_duration_to_minutes("还有2小时") == 120

def test_parse_zero_or_expired():
    assert parse_duration_to_minutes("已过期") == 0

def test_parse_none_when_no_number():
    assert parse_duration_to_minutes("看广告领时长") is None

def test_norm_to_pixel():
    assert norm_to_pixel(0.5, 0.5, 1080, 2400) == (540, 1200)

def test_find_keyword_bounds_hit():
    xml = '<hierarchy><node text="看广告领时长" bounds="[100,200][300,260]"/></hierarchy>'
    assert find_keyword_bounds(xml, ["看广告"]) == (200, 230)

def test_find_keyword_bounds_miss():
    xml = '<hierarchy><node text="设置" bounds="[0,0][10,10]"/></hierarchy>'
    assert find_keyword_bounds(xml, ["看广告"]) is None

def test_extract_duration_from_xml_hit():
    xml = ('<hierarchy>'
           '<node text="看广告" bounds="[0,0][10,10]"/>'
           '<node content-desc="当前可听 剩余3小时20分" bounds="[0,0][10,10]"/>'
           '</hierarchy>')
    assert extract_duration_from_xml(xml) == 200

def test_extract_duration_from_xml_miss():
    xml = '<hierarchy><node text="看广告领时长" bounds="[0,0][10,10]"/></hierarchy>'
    assert extract_duration_from_xml(xml) is None

def test_parse_required_seconds():
    assert parse_required_seconds("点击广告浏览15秒,即可领取") == 15
    assert parse_required_seconds("看 30 秒可得奖励") == 30
    assert parse_required_seconds("免费领取") is None

def test_decide_action_watch_entry():
    assert decide_action("弹窗里有蓝色按钮『点击去浏览』看广告领30分钟免费听歌")["action"] == "watch"

def test_decide_action_back_treasure_not_watch():
    # 含『看广告』但属夺宝/红包 → 不应去看广告，应返回
    assert decide_action("看广告夺宝机会+1，宝箱里有金币现金")["action"] == "back"

def test_decide_action_back_distraction():
    assert decide_action("这是酷狗内测版邀请页面，有立即升级按钮")["action"] == "back"

def test_decide_action_close_reward():
    assert decide_action("恭喜你已获得30分钟免费听歌奖励")["action"] == "close"

def test_decide_action_done_home():
    assert decide_action("这是酷狗主页推荐页，底部有乐库电台")["action"] == "done"

def test_parse_required_seconds_via_parse_required():
    from parsers import parse_required_seconds as prs
    assert prs("浏览15秒即可领取") == 15

def test_parse_decision_watch():
    from parsers import parse_decision
    d = parse_decision("分析后：ACTION=WATCH; LABEL=点击去浏览; SECONDS=15")
    assert d == {"action": "watch", "label": "点击去浏览", "seconds": 15}

def test_parse_decision_back_no_label():
    from parsers import parse_decision
    d = parse_decision("ACTION=BACK; LABEL=无")
    assert d["action"] == "back" and d["label"] == "" and d["seconds"] is None

def test_parse_decision_invalid_returns_none():
    from parsers import parse_decision
    assert parse_decision("这是一段没有结构化动作的描述") is None
    assert parse_decision("ACTION=FLY") is None

def test_parse_watch_progress():
    from parsers import parse_watch_progress
    assert parse_watch_progress("已看2/5条") == (2, 5)
    assert parse_watch_progress("观看5条得全天听") == (0, 5)
    assert parse_watch_progress("免费领取") is None

def test_classify_task_mode():
    from parsers import classify_task_mode
    assert classify_task_mode("观看5条广告得全天听，进度0/5") == "batch"
    assert classify_task_mode("看广告立即得30分钟，每看一个加时长") == "scattered"
    assert classify_task_mode("看一个广告得30分钟；另有观看5条得全天听任务") == "both"
    assert classify_task_mode("这是设置页") == "unknown"

def test_is_distraction_label():
    from parsers import is_distraction_label
    assert is_distraction_label("点击后，看5秒可得夺宝机会") is True
    assert is_distraction_label("马上去用") is True
    assert is_distraction_label("点击去浏览") is False
    assert is_distraction_label("") is False
