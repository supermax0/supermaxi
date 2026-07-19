from types import SimpleNamespace
from unittest.mock import patch

from modules.mobile_app.services import ai_assistant, ai_tools


class _FunctionCall:
    type = "function_call"
    name = "search_products"
    arguments = '{"query":"screen","limit":3}'
    call_id = "call-1"

    def model_dump(self, **_kwargs):
        return {
            "type": self.type,
            "name": self.name,
            "arguments": self.arguments,
            "call_id": self.call_id,
        }


def test_responses_tools_are_strict_and_include_shopper_context():
    definitions = ai_tools.responses_tool_definitions()
    by_name = {item["name"]: item for item in definitions}
    assert "get_shopper_context" in by_name
    assert "compare_products" in by_name
    assert "add_item_to_cart" in by_name
    for definition in definitions:
        assert definition["strict"] is True
        assert definition["parameters"]["additionalProperties"] is False
        assert isinstance(definition["parameters"]["required"], list)


def test_responses_loop_executes_tool_and_returns_grounded_meta():
    tool_response = SimpleNamespace(output=[_FunctionCall()], output_text="")
    final_response = SimpleNamespace(
        output=[],
        output_text="The best in-stock option is the test screen.",
    )
    product = {
        "id": 7,
        "name": "Test screen",
        "price": 300000,
        "stock_status": "in_stock",
    }
    with (
        patch(
            "modules.ai_sales.openai_service.create_response",
            side_effect=[tool_response, final_response],
        ) as create_response,
        patch(
            "modules.ai_sales.openai_service.settings_for_profile",
            return_value=SimpleNamespace(chat_model="gpt-test"),
        ),
        patch.object(
            ai_tools,
            "execute_tool",
            return_value={"items": [product], "count": 1},
        ) as execute_tool,
        patch.object(ai_assistant, "_record_tool"),
    ):
        text, meta = ai_assistant._openai_reply(3, 9, [], "I need a screen")

    assert "test screen" in text
    assert meta["products"] == [product]
    execute_tool.assert_called_once_with(
        "search_products", {"query": "screen", "limit": 3}, user_id=3
    )
    assert create_response.call_count == 2
    second_input = create_response.call_args_list[1].kwargs["input"]
    assert any(item.get("type") == "function_call_output" for item in second_input)
