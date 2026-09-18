from types import SimpleNamespace

import pytest

from study.delivery import ensure_item
from study.storage import Store


def test_ambiguous_upload_recovers_from_cloud_without_duplicate(tmp_path):
    store = Store(tmp_path)
    items = []
    calls = []

    def upload(name, **_):
        calls.append(name)
        items.append(
            SimpleNamespace(
                id="created", parent="", visibleName=name, is_collection=True
            )
        )
        raise TimeoutError("reply lost")

    client = SimpleNamespace(list_items=lambda **_: items, put_folder=upload)
    with pytest.raises(TimeoutError):
        ensure_item(store, client, name="Prepared")
    assert ensure_item(store, client, name="Prepared") == "created"
    assert calls == ["Prepared"]


def test_uncertain_upload_never_blindly_recreates(tmp_path):
    store = Store(tmp_path)
    calls = []

    def upload(name, **_):
        calls.append(name)
        raise TimeoutError("reply lost")

    client = SimpleNamespace(list_items=lambda **_: [], put_folder=upload)
    with pytest.raises(TimeoutError):
        ensure_item(store, client, name="Prepared")
    with pytest.raises(RuntimeError, match="uncertain"):
        ensure_item(store, client, name="Prepared")
    assert len(calls) == 1
