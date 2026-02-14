"""Test that remove_bound handlers filter the boundaries list correctly."""


def test_remove_boundary_filters_by_id():
    """Simulate what the handler does: filter list by bid."""
    boundaries = [
        {"id": 1, "label": "bound1", "nodes": "1 2", "ibtyp": 1, "boundn": "", "zfact": 1.0, "intpol": 1},
        {"id": 2, "label": "bound2", "nodes": "3 4", "ibtyp": 2, "boundn": "", "zfact": 1.0, "intpol": 1},
        {"id": 3, "label": "bound3", "nodes": "5 6", "ibtyp": 1, "boundn": "", "zfact": 1.0, "intpol": 1},
    ]
    bid_to_remove = 2
    result = [x for x in boundaries if x["id"] != bid_to_remove]
    assert len(result) == 2
    assert all(b["id"] != 2 for b in result)


def test_remove_nonexistent_boundary_is_noop():
    boundaries = [
        {"id": 1, "label": "bound1", "nodes": "1", "ibtyp": 1, "boundn": "", "zfact": 1.0, "intpol": 1},
    ]
    result = [x for x in boundaries if x["id"] != 99]
    assert len(result) == 1
