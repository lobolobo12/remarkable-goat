"""Read-only reMarkable cloud sync. Original notebooks are never modified."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID

from pypdf import PdfReader

from .models import Source
from .storage import Store, write_json


def renderer_command():
    local = Path(sys.executable).with_name("remarks")
    return str(local) if local.exists() else shutil.which("remarks")


def renderer_environment():
    env = os.environ.copy()
    if sys.platform == "darwin":
        paths = [
            str(p)
            for p in [Path("/opt/homebrew/lib"), Path("/usr/local/lib")]
            if p.exists()
        ]
        if env.get("DYLD_FALLBACK_LIBRARY_PATH"):
            paths.append(env["DYLD_FALLBACK_LIBRARY_PATH"])
        env["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(paths)
    return env


def client_for(store: Store):
    from remarkapy import Client

    if not store.token_file.exists():
        raise RuntimeError("reMarkable automation is not paired. Run: study pair")
    return Client(configfile=store.token_file, interactive=False, timeout=60)


def descendants(items, folder_id: str):
    by_id = {str(item.id): item for item in items}
    if folder_id not in by_id or not by_id[folder_id].is_collection:
        raise ValueError("Mapped test folder no longer exists")
    # Check ancestors too: a folder inside Trash must not be ingested.
    parent, seen = folder_id, set()
    while parent in by_id:
        if parent in seen:
            raise ValueError("Folder hierarchy contains a cycle")
        seen.add(parent)
        parent = str(by_id[parent].parent)
    if parent == "trash":
        raise ValueError("Mapped test folder is in Trash")
    selected, pending, seen = [], [folder_id], set()
    while pending:
        parent = pending.pop()
        if parent in seen:
            raise ValueError("Folder hierarchy contains a cycle")
        seen.add(parent)
        for item in items:
            if str(item.parent) != parent:
                continue
            if item.is_collection:
                pending.append(str(item.id))
            else:
                selected.append(item)
    return sorted(selected, key=lambda item: str(item.id))


def check_bundle(data: bytes):
    # Reject traversal and oversized archives before passing them to a renderer.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 500_000_000:
            raise ValueError("Notebook bundle exceeds 500 MB expanded limit")
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
                raise ValueError("Unsafe notebook archive path")


def sync_folder(store: Store, client, folder_id: str, items) -> list[Source]:
    documents = descendants(items, folder_id)
    sources = sync_documents(store, client, documents)
    write_json(
        store.private / "folders" / f"{folder_id}.json",
        [source.model_dump(mode="json") for source in sources],
    )
    return sources


def selected_documents(items, identifiers):
    by_id = {str(item.id): item for item in items}
    selected = {}
    for identifier in {str(UUID(str(value))) for value in identifiers}:
        if identifier not in by_id:
            raise ValueError("Izbrani zapisek ali mapa ne obstaja več. Posodobi izbor.")
        item = by_id[identifier]
        current, seen = item, set()
        while current is not None:
            key = str(current.id)
            if key in seen or str(current.parent) == "trash":
                raise ValueError("Izbor vsebuje izbrisano ali neveljavno mapo.")
            seen.add(key)
            if current.visibleName == "Učna priprava" and not current.parent:
                raise ValueError("Ustvarjenega gradiva ni mogoče izbrati kot vir.")
            parent = str(current.parent)
            if parent and parent not in by_id:
                raise ValueError("Izbrani dokument ima neznano nadrejeno mapo.")
            current = by_id.get(parent)
        documents = descendants(items, identifier) if item.is_collection else [item]
        selected.update({str(doc.id): doc for doc in documents})
    return sorted(selected.values(), key=lambda item: str(item.id))


def sync_selection(store, client, identifiers, items):
    return sync_documents(store, client, selected_documents(items, identifiers))


def sync_documents(store, client, documents):
    renderer = renderer_command()
    if not renderer:
        raise RuntimeError("Notebook renderer missing. Run: uv sync --extra cloud")
    if not documents:
        raise ValueError("Izbor nima zapiskov. Dodaj zapiske ali izberi drugo mapo.")
    sources = []
    for item in documents:
        source_id = UUID(str(item.id))
        cache = store.private / "notebooks" / str(source_id) / item.hash
        pdf = cache / "pages.pdf"
        if not pdf.exists():
            data = client.get_document(item.hash)
            check_bundle(data)
            cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=cache) as tmp:
                stage = Path(tmp)
                bundle = stage / f"{source_id}.rmdoc"
                bundle.write_bytes(data)
                output = stage / "rendered"
                output.mkdir()
                # Chrome is used by the renderer solely to render local SVG to PDF.
                process = subprocess.run(
                    [renderer, str(bundle), str(output)],
                    capture_output=True,
                    timeout=300,
                    check=False,
                    env=renderer_environment(),
                )
                if process.returncode:
                    raise RuntimeError(
                        f"PDF rendering failed for {item.visibleName}; source not replaced"
                    )
                candidates = list(output.rglob("*.pdf"))
                if len(candidates) != 1:
                    raise RuntimeError(
                        f"Expected one complete PDF for {item.visibleName}"
                    )
                if not PdfReader(candidates[0]).pages:
                    raise RuntimeError("Renderer returned an empty PDF")
                shutil.copyfile(candidates[0], cache / "pages.tmp")
                os.replace(cache / "pages.tmp", pdf)
        sources.append(
            Source(
                id=source_id,
                name=item.visibleName,
                hash=item.hash,
                pdf=str(pdf.relative_to(store.root)),
            )
        )
    return sources


def cached_sources(store: Store, folder_id: str) -> list[Source]:
    path = store.private / "folders" / f"{UUID(folder_id)}.json"
    return [Source.model_validate(row) for row in json.loads(path.read_text())]
