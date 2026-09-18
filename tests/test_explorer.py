from types import SimpleNamespace
from uuid import uuid4

from study.explorer import library_tree
from study.storage import Store


def item(name, parent="", folder=True, **extra):
    return SimpleNamespace(
        id=str(uuid4()),
        visibleName=name,
        parent=parent,
        is_collection=folder,
        hash="version1",
        **extra,
    )


def test_library_keeps_nested_documents_and_excludes_trash_cycles_and_orphans(tmp_path):
    store = Store(tmp_path)
    root = item("Geografija")
    sub = item("Test 1", root.id)
    note = item("Podnebje", sub.id, False)
    deleted = item("Deleted", "trash")
    hidden = item("Hidden", deleted.id, False)
    orphan = item("Orphan", "missing")
    loop = item("Loop")
    loop.parent = loop.id
    generated = item("Učna priprava")
    output = item("Vaje", generated.id, False)
    preview = store.private / "notebooks" / note.id / note.hash / "pages.pdf"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"cached PDF fixture")
    tree = library_tree(
        store, [note, hidden, root, sub, deleted, orphan, loop, generated, output]
    )
    assert [n["name"] for n in tree] == ["Geografija", "Učna priprava"]
    nested = tree[0]["children"][0]["children"][0]
    assert nested["name"] == "Podnebje" and nested["children"] is None
    assert nested["path"] == "Geografija / Test 1 / Podnebje"
    assert nested["preview_path"] == str(preview)
    assert tree[0]["children"][0]["can_select"]
    assert not tree[1]["can_select"] and tree[1]["children"][0]["name"] == "Vaje"
    assert preview.read_bytes() == b"cached PDF fixture"


def test_multi_selection_expands_folders_deduplicates_and_isolates_sources():
    from study.cloud import selected_documents

    root = item("Geografija")
    sub = item("Test 1", root.id)
    one = item("Podnebje", sub.id, False)
    two = item("Rastje", sub.id, False)
    excluded = item("Drugi test", root.id, False)
    items = [root, sub, one, two, excluded]
    assert {d.id for d in selected_documents(items, [one.id, two.id])} == {
        one.id,
        two.id,
    }
    assert {d.id for d in selected_documents(items, [sub.id, one.id, sub.id])} == {
        one.id,
        two.id,
    }
    new_note = item("Novi zapiski", sub.id, False)
    assert {d.id for d in selected_documents(items + [new_note], [sub.id])} == {
        one.id,
        two.id,
        new_note.id,
    }


def test_selected_deleted_or_generated_documents_are_rejected():
    import pytest

    from study.cloud import selected_documents

    trash = item("Removed", "trash")
    deleted = item("note", trash.id, False)
    output = item("Učna priprava")
    generated = item("vaje", output.id, False)
    items = [trash, deleted, output, generated]
    for identifier in [deleted.id, generated.id, str(uuid4())]:
        with pytest.raises(ValueError):
            selected_documents(items, [identifier])
