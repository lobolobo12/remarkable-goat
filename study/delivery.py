"""Append-only delivery into a separate reMarkable preparation folder."""

import json

from .storage import write_json

ROOT_NAME = "Učna priprava"


def ensure_item(store, client, *, name, parent="", pdf=None):
    from .storage import digest

    key = digest((parent + "\n" + name).encode())
    pending = store.private / "delivery-pending" / f"{key}.json"
    matches = [
        item
        for item in client.list_items(refresh=True)
        if str(item.parent) == parent and item.visibleName == name
    ]
    if len(matches) > 1:
        raise RuntimeError(
            "Duplicate delivery destination names; select a single preparation folder."
        )
    if matches:
        match = matches[0]
        if bool(match.is_collection) != (pdf is None):
            raise RuntimeError("Delivery destination type does not match.")
        pending.unlink(missing_ok=True)
        return str(match.id)
    if pending.exists():
        raise RuntimeError(
            "A previous tablet upload had an uncertain result. Check the preparation folder before retrying; no duplicate was created."
        )
    write_json(pending, {"name": name, "parent": parent})
    item = (
        client.put_folder(name, parent=parent, refresh=True)
        if pdf is None
        else client.put_pdf(name, pdf.read_bytes(), parent=parent, refresh=True)
    )
    pending.unlink()
    return str(item.id)


def deliver(store, client, assessment):
    latest = store.output / str(assessment.id) / "latest.json"
    if not latest.exists():
        raise RuntimeError("Study pack has not been published locally.")
    output = (store.root / json.loads(latest.read_text())["path"]).resolve()
    if (
        not output.is_relative_to(store.output.resolve())
        or not (output / "complete.json").exists()
    ):
        raise RuntimeError("Invalid or incomplete study pack output.")
    state_path = output / "delivery.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    root = ensure_item(store, client, name=ROOT_NAME)
    name = f"{assessment.date} - {assessment.subject} - {str(assessment.id)[:8]}"
    test = ensure_item(store, client, name=name, parent=root)
    version = ensure_item(
        store, client, name="Različica " + output.name[:12], parent=test
    )
    documents = {}
    for filename, label in [
        ("zapiski.pdf", "Urejeni zapiski"),
        ("vaje.pdf", "Preizkus za vajo"),
        ("resitve.pdf", "Rešitve in točkovnik"),
    ]:
        documents[filename] = ensure_item(
            store, client, name=label, parent=version, pdf=output / filename
        )
    result = {"status": "delivered", "folder_id": version, "documents": documents}
    write_json(state_path, result)
    return result
