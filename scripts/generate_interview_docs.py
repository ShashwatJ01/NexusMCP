from __future__ import annotations

import datetime as dt
import html
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "INTERVIEW_PREP_AGENT_MCP_GUIDE.md"
DOCX_OUTPUT = ROOT / "INTERVIEW_PREP_AGENT_MCP_GUIDE.docx"
PDF_OUTPUT = ROOT / "INTERVIEW_PREP_AGENT_MCP_GUIDE.pdf"


def parse_markdown(markdown_text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            blocks.append(("blank", ""))
            continue
        if line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
            continue
        if line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
            continue
        if line.startswith("### "):
            blocks.append(("h3", line[4:].strip()))
            continue
        if line.startswith("- "):
            blocks.append(("bullet", line[2:].strip()))
            continue
        blocks.append(("p", line))
    return blocks


def normalize_inline(text: str) -> str:
    return text.replace("`", "")


def paragraph_xml(text: str, style: str | None = None, bullet: bool = False) -> str:
    text = escape(normalize_inline(text))
    p_style = f"<w:pStyle w:val=\"{style}\"/>" if style else ""
    bullet_xml = ""
    if bullet:
        bullet_xml = "<w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr>"
    return (
        "<w:p>"
        f"<w:pPr>{p_style}{bullet_xml}</w:pPr>"
        f"<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r>"
        "</w:p>"
    )


def build_docx(markdown_text: str) -> None:
    blocks = parse_markdown(markdown_text)
    body = []
    for kind, text in blocks:
        if kind == "blank":
            body.append("<w:p/>")
        elif kind == "h1":
            body.append(paragraph_xml(text, style="Title"))
        elif kind == "h2":
            body.append(paragraph_xml(text, style="Heading2"))
        elif kind == "h3":
            body.append(paragraph_xml(text, style="Heading3"))
        elif kind == "bullet":
            body.append(paragraph_xml(text, bullet=True))
        else:
            body.append(paragraph_xml(text))

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/wordprocessingml/2006/main"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 mc:Ignorable="w14 wp14">
<w:body>
{''.join(body)}
<w:sectPr>
<w:pgSz w:w="12240" w:h="15840"/>
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>
</w:sectPr>
</w:body>
</w:document>"""

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:numbering />
</w:styles>"""

    numbering = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:abstractNum w:abstractNumId="0">
<w:lvl w:ilvl="0">
<w:numFmt w:val="bullet"/>
<w:lvlText w:val="•"/>
<w:lvlJc w:val="left"/>
</w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""

    created = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    core = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>Agent, Model, MCP, and Tooling Interview Guide</dc:title>
<dc:creator>Codex</dc:creator>
<cp:lastModifiedBy>Codex</cp:lastModifiedBy>
<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
<dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>"""

    app = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
<Application>Codex</Application>
</Properties>"""

    with zipfile.ZipFile(DOCX_OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/_rels/document.xml.rels", doc_rels)
        docx.writestr("word/styles.xml", styles)
        docx.writestr("word/numbering.xml", numbering)
        docx.writestr("docProps/core.xml", core)
        docx.writestr("docProps/app.xml", app)


def wrap_text(text: str, width: int) -> list[str]:
    words = normalize_inline(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(markdown_text: str) -> None:
    blocks = parse_markdown(markdown_text)
    page_width = 612
    page_height = 792
    margin = 54
    y = page_height - margin
    lines_per_page: list[list[tuple[str, int]]] = [[]]

    def add_line(line: str, font_size: int) -> None:
        nonlocal y
        needed = font_size + 6
        if y - needed < margin:
            lines_per_page.append([])
            y = page_height - margin
        lines_per_page[-1].append((line, font_size))
        y -= needed

    for kind, text in blocks:
        if kind == "blank":
            add_line("", 12)
        elif kind == "h1":
            for line in wrap_text(text, 60):
                add_line(line, 20)
            add_line("", 12)
        elif kind == "h2":
            for line in wrap_text(text, 70):
                add_line(line, 16)
        elif kind == "h3":
            for line in wrap_text(text, 74):
                add_line(line, 14)
        elif kind == "bullet":
            for index, line in enumerate(wrap_text(text, 82)):
                prefix = "• " if index == 0 else "  "
                add_line(f"{prefix}{line}", 12)
        else:
            for line in wrap_text(text, 88):
                add_line(line, 12)

    objects: list[bytes] = []

    def add_object(data: str | bytes) -> int:
        if isinstance(data, str):
            data = data.encode("utf-8")
        objects.append(data)
        return len(objects)

    font_regular_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_ids: list[int] = []
    content_ids: list[int] = []

    for page_lines in lines_per_page:
        content_commands = ["BT"]
        current_y = page_height - margin
        for line, font_size in page_lines:
            font_name = "F2" if font_size >= 14 else "F1"
            content_commands.append(f"/{font_name} {font_size} Tf")
            content_commands.append(f"1 0 0 1 {margin} {current_y} Tm")
            content_commands.append(f"({escape_pdf_text(line)}) Tj")
            current_y -= font_size + 6
        content_commands.append("ET")
        content_stream = "\n".join(content_commands).encode("utf-8")
        content_id = add_object(
            b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n" + content_stream + b"\nendstream"
        )
        content_ids.append(content_id)
        page_obj = (
            "<< /Type /Page /Parent {parent} 0 R "
            f"/MediaBox [0 0 {page_width} {page_height}] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> >>"
        )
        page_ids.append(add_object(page_obj))

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    pages_id = add_object(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>")

    for index, page_id in enumerate(page_ids):
        page_text = objects[page_id - 1].decode("utf-8").replace("{parent}", str(pages_id))
        objects[page_id - 1] = page_text.encode("utf-8")

    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )

    PDF_OUTPUT.write_bytes(pdf)


def main() -> None:
    markdown_text = SOURCE.read_text(encoding="utf-8")
    build_docx(markdown_text)
    build_pdf(markdown_text)
    print(f"Created {DOCX_OUTPUT.name} and {PDF_OUTPUT.name}")


if __name__ == "__main__":
    main()
