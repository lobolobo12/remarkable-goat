from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from .models import Pack, Source
from .storage import write_json


def render_pack(pack: Pack, sources: list[Source], destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    fonts = [
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font = next((path for path in fonts if path.exists()), None)
    if font is None:
        raise RuntimeError("A Unicode font is needed: install DejaVu Sans")
    if "Study" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Study", str(font)))
    styles = {
        "title": ParagraphStyle(
            "title", fontName="Study", fontSize=23, leading=29, spaceAfter=18
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName="Study",
            fontSize=14,
            leading=19,
            spaceBefore=15,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body", fontName="Study", fontSize=11, leading=17, spaceAfter=9
        ),
        "small": ParagraphStyle(
            "small",
            fontName="Study",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#555555"),
            spaceAfter=9,
        ),
    }
    names = {str(source.id): source.name for source in sources}

    def paragraph(text, style="body"):
        return Paragraph(escape(text).replace("\n", "<br/>"), styles[style])

    def refs(references):
        return "; ".join(f"{names[r.source_id]}, str. {r.page}" for r in references)

    def save(filename, label, content):
        story = [paragraph(label, "title"), paragraph(pack.title, "heading")]
        story.extend(content)

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Study", 9)
            canvas.setFillColor(colors.HexColor("#666666"))
            canvas.drawString(48, 28, "Priprava iz lastnih zapiskov")
            canvas.drawRightString(A4[0] - 48, 28, str(doc.page))
            canvas.restoreState()

        SimpleDocTemplate(
            str(destination / filename),
            pagesize=A4,
            leftMargin=48,
            rightMargin=48,
            topMargin=45,
            bottomMargin=48,
        ).build(story, onFirstPage=footer, onLaterPages=footer)

    notes = []
    for section in pack.sections:
        notes += [
            paragraph(section.title, "heading"),
            paragraph(section.explanation),
            paragraph("Vir: " + refs(section.references), "small"),
        ]
    if pack.warnings:
        notes.append(paragraph("Preveri v zapiskih", "heading"))
        notes.extend(paragraph(warning) for warning in pack.warnings)
    notes.append(paragraph("Načrt učenja", "heading"))
    notes.extend(
        paragraph(f"Dan {day.day} ({day.minutes} min): {day.task}")
        for day in pack.schedule
    )
    save("zapiski.pdf", "Urejeni zapiski", notes)
    test, answers = [], []
    test.append(
        paragraph(
            f"Skupaj: {sum(q.points for q in pack.questions)} točk. "
            "Vaje temeljijo na tvojih zapiskih; niso napoved učiteljevega testa.",
            "small",
        )
    )
    for i, question in enumerate(pack.questions, 1):
        heading = f"Naloga {i} ({question.points} točk)"
        question_block = [paragraph(heading, "heading"), paragraph(question.question)]
        for _ in range(5):
            question_block.extend(
                [
                    Spacer(1, 18),
                    HRFlowable(
                        width="100%", thickness=0.4, color=colors.HexColor("#cccccc")
                    ),
                ]
            )
        test.append(KeepTogether(question_block))
        answers.append(
            KeepTogether(
                [
                    paragraph(heading, "heading"),
                    paragraph(question.answer),
                    paragraph("Ocenjevanje: " + question.marking),
                    paragraph("Vir: " + refs(question.references), "small"),
                ]
            )
        )
    save("vaje.pdf", "Preizkus za vajo", test)
    save("resitve.pdf", "Rešitve in točkovnik", answers)
    write_json(destination / "pack.json", pack.model_dump())
    write_json(
        destination / "sources.json",
        [source.model_dump(mode="json") for source in sources],
    )
    lines = ["# " + pack.title, ""]
    for section in pack.sections:
        lines.extend(
            [
                "## " + section.title,
                section.explanation,
                "Vir: " + refs(section.references),
                "",
            ]
        )
    lines += ["## Preveri", *pack.warnings, "", "## Načrt učenja"]
    lines += [f"Dan {day.day} ({day.minutes} min): {day.task}" for day in pack.schedule]
    (destination / "zapiski.md").write_text("\n".join(lines), encoding="utf-8")
