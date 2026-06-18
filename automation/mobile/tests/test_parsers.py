import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsers import (parse_duration_to_minutes, norm_to_pixel,
                     find_keyword_bounds, extract_duration_from_xml)


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
