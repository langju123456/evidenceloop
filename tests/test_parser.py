from evidenceloop.harness.parser import format_tool_call, parse_assistant_output


def test_roundtrip():
    parsed = parse_assistant_output("先查版本。\n" + format_tool_call("list_versions", {"resource_id": "pr_a_01"}))
    assert parsed.error is None and parsed.calls == [{"name": "list_versions", "arguments": {"resource_id": "pr_a_01"}}]
    assert parsed.content == "先查版本。"


def test_strict_failures():
    assert parse_assistant_output("<tool_call>{bad json}</tool_call>").error
    assert parse_assistant_output('<tool_call>{"name": "x"}</tool_call>').error
    assert parse_assistant_output('<tool_call>{"name": "x", "arguments": "{}"}</tool_call>').error
    assert parse_assistant_output('<tool_call>{"name": "x", "parameters": {}}</tool_call>').error
    assert parse_assistant_output('<tool_call>{"name": "a", "arguments": {}}<tool_call>{"name": "b", "arguments": {}}').error
    assert parse_assistant_output('</tool_call>').error


def test_as_lenient_as_the_reference_hermes_parser_and_no_more():
    unclosed = parse_assistant_output('<tool_call>\n{"name": "x", "arguments": {"a": 1}}')
    assert unclosed.error is None and unclosed.calls == [{"name": "x", "arguments": {"a": 1}}]
    extra = parse_assistant_output('<tool_call>{"name": "x", "arguments": {}, "id": "call_1"}</tool_call>')
    assert extra.error is None and extra.calls == [{"name": "x", "arguments": {}}]
    mixed = parse_assistant_output(format_tool_call("a", {}) + '<tool_call>{"name": "b", "arguments": {}}')
    assert [c["name"] for c in mixed.calls] == ["a", "b"]


def test_empty_think_block_and_final_answer():
    parsed = parse_assistant_output("<think>\n\n</think>\n\n已保存草稿。")
    assert parsed.error is None and parsed.calls == [] and parsed.content == "已保存草稿。"
