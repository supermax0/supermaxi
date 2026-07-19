from modules.ai_sales.engine import _history_requested_foot_size


def test_split_fridge_size_across_recent_messages():
    history = [
        {"role": "user", "content": "\u062b\u0644\u0627\u062c\u0647"},
        {"role": "user", "content": "7"},
    ]

    assert _history_requested_foot_size(history, "\u0642\u062f\u0645", {}) == 7


def test_split_fridge_size_overrides_old_fact():
    history = [
        {"role": "user", "content": "\u062b\u0644\u0627\u062c\u0647"},
        {"role": "user", "content": "7"},
        {"role": "user", "content": "\u0642\u062f\u0645"},
    ]

    assert _history_requested_foot_size(history, "\u0633\u0639\u0631\u0647 \u062c\u0645\u0644\u0647", {"requested_foot_size": 5}) == 7


def test_split_fridge_size_without_fridge_word_does_not_guess():
    history = [{"role": "user", "content": "7"}]

    assert _history_requested_foot_size(history, "\u0642\u062f\u0645", {}) is None


def test_joined_burst_foot_size_overrides_old_fact():
    text = "\n".join([
        "\u0631\u0633\u0627\u0644\u0629 \u0627\u0644\u0632\u0628\u0648\u0646 1: \u062b\u0644\u0627\u062c\u0647",
        "\u0631\u0633\u0627\u0644\u0629 \u0627\u0644\u0632\u0628\u0648\u0646 2: 7",
        "\u0631\u0633\u0627\u0644\u0629 \u0627\u0644\u0632\u0628\u0648\u0646 3: \u0642\u062f\u0645",
    ])

    assert _history_requested_foot_size([], text, {"requested_foot_size": 5}) == 7
