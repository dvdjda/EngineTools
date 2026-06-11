"""Commercial-style one-page PDF report for a LiBr chiller sizing case."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image, Frame, PageTemplate)
from reportlab.lib.enums import TA_LEFT

from .charts import make_chart, design_rows, result_rows

NAVY = colors.HexColor("#2E4E7E")
TEAL = colors.HexColor("#2BB6A3")
LIGHT = colors.HexColor("#EAF0F8")
GREY = colors.HexColor("#595959")
INK = colors.HexColor("#22303F")


def _styles():
    ss = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold",
                             fontSize=18, textColor=NAVY, alignment=TA_LEFT,
                             spaceAfter=14, leading=24),
        "sub": ParagraphStyle("sub", fontName="Helvetica-Oblique", fontSize=9.5,
                              textColor=GREY, spaceAfter=10),
        "sec": ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=11,
                              textColor=NAVY, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9,
                               textColor=INK, leading=12),
    }


def _kv_table(rows, width):
    data = [[n, v, u] for (n, v, u) in rows]
    t = Table(data, colWidths=[width * 0.6, width * 0.22, width * 0.18])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D2E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 8),
    ]))
    return t


def build_pdf(dp, r, path, chart_png):
    make_chart(r, chart_png)
    st = _styles()
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    W = doc.width
    story = []

    story.append(Paragraph("Single-effect LiBr-H<sub>2</sub>O absorption chiller", st["h1"]))
    story.append(Paragraph("Screening sizing report  &nbsp;|&nbsp;  Nexa Block v1  "
                           "&nbsp;|&nbsp;  verify duties vs ChemCAD", st["sub"]))

    # two columns of tables: design point | key results
    story.append(Spacer(1, 2))
    left = [Paragraph("Design point", st["sec"]), _kv_table(design_rows(dp), W * 0.46)]
    right = [Paragraph("Key results", st["sec"]), _kv_table(result_rows(r), W * 0.46)]
    cols = Table([[left, right]], colWidths=[W * 0.5, W * 0.5])
    cols.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
    ]))
    story.append(cols)

    story.append(Paragraph("Duties and crystallisation margin", st["sec"]))
    story.append(Image(chart_png, width=W, height=W * 3.5 / 9.2))

    story.append(Spacer(1, 6))
    note = ("Method: water and steam properties from CoolProp (IAPWS); LiBr-H2O "
            "equilibrium from the ASHRAE / Herold-Klein Duhring relation; solution "
            "enthalpy from the ASHRAE polynomial. Concentration and crystallisation "
            "figures are solid screening numbers; absolute duties are screening-grade "
            "and depend on the enthalpy correlations. ChemCAD remains the system of "
            "record for certifiable numbers.")
    story.append(Paragraph(note, st["body"]))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(2)
        canvas.line(18 * mm, A4[1] - 12 * mm, A4[0] - 18 * mm, A4[1] - 12 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 10 * mm, "Nexa Power Investments LLC - Confidential")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, "Screening report - not for certification")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path
