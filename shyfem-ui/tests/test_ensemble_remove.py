"""Test that remove_var handlers pop the correct variation."""


def test_remove_variation_by_index():
    variations = [
        {"section": "para", "param": "czdef", "values": "0.02, 0.03"},
        {"section": "para", "param": "idt", "values": "10, 30"},
        {"section": "para", "param": "ahpar", "values": "1, 5"},
    ]
    index_to_remove = 1
    current = list(variations)
    current.pop(index_to_remove)
    assert len(current) == 2
    assert current[0]["param"] == "czdef"
    assert current[1]["param"] == "ahpar"


def test_remove_last_variation():
    variations = [
        {"section": "para", "param": "czdef", "values": "0.02"},
        {"section": "para", "param": "idt", "values": "10"},
    ]
    current = list(variations)
    current.pop(1)
    assert len(current) == 1
    assert current[0]["param"] == "czdef"
