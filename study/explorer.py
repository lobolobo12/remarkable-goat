"""Read-only, cached reMarkable library tree for the native file explorer."""


def library_tree(store, items):
    by_id = {str(item.id): item for item in items}
    nodes = {}
    for identifier, item in by_id.items():
        current, seen, names = item, set(), []
        valid = True
        while current is not None:
            key = str(current.id)
            if key in seen or str(current.parent) == "trash":
                valid = False
                break
            seen.add(key)
            names.insert(0, current.visibleName)
            parent = str(current.parent)
            if parent and parent not in by_id:
                valid = False
                break
            current = by_id.get(parent)
        if not valid:
            continue
        preview = (
            store.private
            / "notebooks"
            / identifier
            / str(getattr(item, "hash", ""))
            / "pages.pdf"
        )
        # Show only locally rendered PDFs within this workflow's source cache.
        safe_preview = preview.resolve().is_relative_to(
            (store.private / "notebooks").resolve()
        )
        nodes[identifier] = {
            "id": identifier,
            "name": item.visibleName,
            "path": " / ".join(names),
            "parent": str(item.parent),
            "is_folder": item.is_collection,
            "can_select": names[0] != "Učna priprava",
            "preview_path": str(preview)
            if safe_preview and preview.is_file()
            else None,
            "children": [] if item.is_collection else None,
        }
    roots = []
    for node in nodes.values():
        parent = nodes.get(node["parent"])
        if parent and parent["children"] is not None:
            parent["children"].append(node)
        elif not node["parent"]:
            roots.append(node)

    def sort(nodes):
        nodes.sort(key=lambda n: (not n["is_folder"], n["name"].casefold(), n["id"]))
        for node in nodes:
            if node["children"] is not None:
                sort(node["children"])

    sort(roots)
    return roots
