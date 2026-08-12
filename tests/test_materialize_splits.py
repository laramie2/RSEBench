from scripts.materialize_splits import _officeqa_connected_items


def test_officeqa_grouping_uses_source_document_connected_components():
    rows = [
        {"uid": "a", "source_files": "one.txt\r\ntwo.txt"},
        {"uid": "b", "source_files": "two.txt\r\nthree.txt"},
        {"uid": "c", "source_files": "separate.txt"},
    ]

    assignments = dict(_officeqa_connected_items(rows))

    assert assignments["a"] == assignments["b"]
    assert assignments["a"] != assignments["c"]
