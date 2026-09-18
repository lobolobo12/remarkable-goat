"""Manual layout QA fixture; no real notes or AI calls."""

from pathlib import Path
from uuid import uuid4

import pymupdf

from study.models import Pack, Question, Reference, Section, Source, StudyDay
from study.output import render_pack

source = Source(
    id=uuid4(), name="Preizkus šumnikov č š ž", hash="fixture", pdf="fixture.pdf"
)
reference = Reference(source_id=str(source.id), page=1)
pack = Pack(
    title="Preizkus postavitve - ni učno gradivo",
    sections=[
        Section(
            title="Slovenski znaki in formule",
            explanation="Črke č, š in ž morajo biti berljive. Primer: x^2 + y^2 = z^2. "
            "Odstavki imajo dovolj prostora za branje na tablici.\nDruga vrstica preverja razmik.",
            references=[reference],
        ),
        Section(
            title="Daljša razlaga",
            explanation="To je izmišljeno besedilo za preverjanje preloma strani. "
            * 35,
            references=[reference],
        ),
    ],
    questions=[
        Question(
            question="Napiši odgovor na prvo vprašanje. To besedilo preverja prostor za rokopis.",
            points=3,
            answer="Vzorčna rešitev z znaki č, š, ž.",
            marking="Ena točka za vsak utemeljen korak.",
            references=[reference],
        ),
        Question(
            question="Pojasni svoj postopek in zapiši enačbo x^2 = 4.",
            points=2,
            answer="x = 2 ali x = -2.",
            marking="Dve točki za oba rezultata.",
            references=[reference],
        ),
    ],
    warnings=[
        "To je zgolj preizkus postavitve; nobeno gradivo ni bilo poslano API-ju."
    ],
    schedule=[
        StudyDay(day=i, task="Preberi, ponovi in preveri razumevanje.")
        for i in range(1, 8)
    ],
)
out = Path("tmp/pdfs/qa")
render_pack(pack, [source], out)
for path in out.glob("*.pdf"):
    with pymupdf.open(path) as document:
        for index, page in enumerate(document):
            page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(
                out / f"{path.stem}-{index + 1}.png"
            )
        print(path.name, len(document), "pages")
