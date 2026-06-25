"""judge 解析与适配测试（不打真实 LLM）。"""
from __future__ import annotations

from app.eval import judge


def test_parse_plain_json():
    raw = '{"helpfulness": 5, "correctness": 4, "safety": 5, "reasoning": "好"}'
    out = judge._parse(raw)
    assert out == {"helpfulness": 5, "correctness": 4, "safety": 5, "reasoning": "好"}


def test_parse_markdown_wrapped():
    raw = '```json\n{"helpfulness": 3, "correctness": 3, "safety": 4}\n```'
    out = judge._parse(raw)
    assert out["helpfulness"] == 3 and out["safety"] == 4


def test_parse_drops_out_of_range():
    raw = '{"helpfulness": 9, "correctness": 4, "safety": 5}'
    out = judge._parse(raw)
    assert "helpfulness" not in out  # 9 越界被丢
    assert out["correctness"] == 4


def test_parse_returns_none_on_garbage():
    assert judge._parse("not json at all") is None


def test_extract_qa_from_sample():
    q, a = judge._extract_qa(({"user_input": "Q", "answer": "A"},))
    assert (q, a) == ("Q", "A")


def test_extract_qa_from_case_and_turn():
    case = {"user_input": "Q"}
    turn = {"eval_samples": [{"answer": "first"}, {"answer": "last"}]}
    q, a = judge._extract_qa((case, turn))
    assert q == "Q" and a == "last"


def test_make_judge_fn_skips_empty_answer():
    fn = judge.make_judge_fn(llm_gateway=None)
    assert fn({"user_input": "Q", "answer": ""}) is None
