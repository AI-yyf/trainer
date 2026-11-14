import pytest

from app.evaluator.service import EvaluatorService


def acceptance(code: str, symbols: list[str], criteria: list[str] | None = None):
    return EvaluatorService()._training_acceptance_check(
        source="training", code=code, language_id="python",
        acceptance_criteria=criteria or [], learner_deliverables=[],
        expected_symbols=symbols, execution_passed=True,
    )


def test_nested_list_calls_and_negative_hash_paths_are_real_code_signals():
    code = """
pair = ([1, 2], 3)
pair [0] . append(4)
value = ([1, 2], 3)
try:
    hash(value)
except TypeError:
    pass
try:
    {value: 1}
except TypeError:
    pass
"""
    result = acceptance(code, ["pair[0].append", "hash(value)", "{value: 1}", "TypeError"],
                        ["调用 `pair[0].append` 修改内部列表", "验证 `hash(value)` 的边界"])
    assert result is not None and result.status == "passed"


@pytest.mark.parametrize("code", [
    '# pair[0].append(4)\ntext = "hash(value), {value: 1}"',
    'text = "pair[0].append(4)"\n# hash(value), {value: 1}',
    "pair[1].append(4)\nhash(other)\n{other: 1}",
    "pair[0] = []\nvalue = 1",
])
def test_expression_lookalikes_do_not_verify_missing_operations(code):
    result = acceptance(code, ["pair[0].append", "hash(value)", "{value: 1}"])
    assert result is not None and result.status == "failed"


def test_expression_inside_string_argument_does_not_count_as_executed_code():
    result = acceptance('print("pair[0].append(4)")', ["pair[0].append"])
    assert result is not None and result.status == "failed"


def test_assignment_to_expression_does_not_count_as_reading_or_calling_it():
    result = acceptance("pair[0].append = custom_append", ["pair[0].append"])
    assert result is not None and result.status == "failed"


def test_nested_and_empty_list_literals_are_matched_as_real_syntax():
    result = acceptance(
        "assert sum_nested([]) == 0\nassert sum_nested([1, [2, [3, 4]], 5]) == 15",
        ["[]", "[1, [2, [3, 4]], 5]"],
    )
    assert result is not None and result.status == "passed"


@pytest.mark.parametrize("code", [
    'text = "[] and [1, [2, [3, 4]], 5]"',
    '# [] and [1, [2, [3, 4]], 5]',
    'assert sum_nested([1, [2, [3, 9]], 5]) == 20',
])
def test_list_literals_in_comments_strings_or_with_wrong_values_do_not_match(code):
    result = acceptance(code, ["[]", "[1, [2, [3, 4]], 5]"])
    assert result is not None and result.status == "failed"


def test_explicit_returned_string_values_can_satisfy_acceptance_signals():
    code = '''
class ConversationState:
    required_context: set[str]
    present_context: set[str]


def next_action(state: ConversationState) -> str:
    missing_context = set(state.required_context) - set(state.present_context)
    if missing_context:
        return "ask_clarification"
    return "answer"
'''
    result = acceptance(
        code,
        ["ConversationState", "next_action", "missing_context",
         "required_context", "present_context", "ask_clarification", "answer"],
        ['定义 `next_action` 在上下文缺失时返回 `"ask_clarification"` 的分支'],
    )
    assert result is not None
    assert result.status == "passed", result.detail


def test_string_values_only_in_comments_do_not_satisfy_symbol_acceptance():
    code = '# return "ask_clarification"\ndef next_action(state):\n    return "answer"\n'
    result = acceptance(code, ["ask_clarification"])
    assert result is not None
    assert result.status == "failed"


def test_function_name_in_a_printed_string_is_not_a_definition():
    result = acceptance('if __name__ == "__main__":\n    print("ppo_clip_loss")\n', ["ppo_clip_loss"])
    assert result is not None
    assert result.status == "failed"
