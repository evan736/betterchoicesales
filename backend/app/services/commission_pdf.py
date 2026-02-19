"""Generate professional commission statement PDFs."""
import io
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


def generate_commission_pdf(sheet_data: dict) -> bytes:
    """Generate a PDF commission sheet from sheet data."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(
        name='CompanyName',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a5632'),
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name='SheetTitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#334155'),
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='AgentInfo',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#475569'),
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=colors.HexColor('#1e293b'),
        spaceBefore=8,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='SmallRight',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_RIGHT,
        textColor=colors.HexColor('#64748b'),
    ))
    styles.add(ParagraphStyle(
        name='TableCell',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=9,
    ))
    styles.add(ParagraphStyle(
        name='TableCellRight',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=9,
        alignment=TA_RIGHT,
    ))

    story = []
    fmt = lambda n: f"${n:,.2f}"
    summary = sheet_data["summary"]

    # ── Header ────────────────────────────────────────────────────
    story.append(Paragraph("Better Choice Insurance", styles['CompanyName']))
    story.append(Paragraph(f"Commission Statement — {sheet_data['period_display']}", styles['SheetTitle']))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1a5632')))
    story.append(Spacer(1, 8))

    # Agent info row
    rate_display = f"Tier {sheet_data['tier_level']} ({sheet_data['commission_rate'] * 100:.1f}%)"
    if sheet_data.get('rate_adjustment', 0) != 0:
        adj = sheet_data['rate_adjustment']
        rate_display += f" [{'+' if adj > 0 else ''}{adj * 100:.1f}% adj]"
    info_data = [
        ["Agent:", sheet_data['agent_name'], "Period:", sheet_data['period_display']],
        ["Role:", sheet_data['agent_role'].replace('_', ' ').title(), "Tier:", rate_display],
        ["Email:", sheet_data['agent_email'] or "—", "Based On:", f"{fmt(sheet_data['tier_premium'])} written premium"],
    ]
    info_table = Table(info_data, colWidths=[0.7 * inch, 2.5 * inch, 0.7 * inch, 3 * inch])
    info_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#475569')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#475569')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 12))

    # ── Summary Box ───────────────────────────────────────────────
    story.append(Paragraph("Summary", styles['SectionHeader']))

    sum_rows = [
        ["New Business Premium", fmt(summary.get("new_business_premium", 0)),
         "Other Paid Premium", fmt(summary.get("other_paid_premium", 0))],
        ["Total Paid Premium", fmt(summary.get("total_paid_premium", 0)),
         "Chargeback Premium", f"{fmt(summary.get('chargeback_premium', 0))} ({summary.get('chargeback_count', 0)})"],
    ]

    # Add bonus row if present
    bonus_amt = summary.get("bonus", 0) or 0
    if bonus_amt > 0:
        sum_rows.append(["Commission", fmt(summary["total_agent_commission"]),
                         "Bonus", fmt(bonus_amt)])
        sum_rows.append(["", "",
                         "Grand Total", fmt(summary.get("grand_total", summary["total_agent_commission"]))])
    else:
        sum_rows.append(["", "",
                         "Total Agent Commission", fmt(summary["total_agent_commission"])])

    # Rate adjustment note
    rate_adj = sheet_data.get("rate_adjustment", 0)
    if rate_adj != 0:
        adj_label = f"Rate Adjustment: {'+' if rate_adj > 0 else ''}{rate_adj * 100:.1f}%"
        sum_rows.insert(-1, [adj_label, "", "", ""])

    sum_table = Table(sum_rows, colWidths=[2 * inch, 1.5 * inch, 2 * inch, 1.5 * inch])
    sum_style = [
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.HexColor('#1a5632')),
        ('FONTNAME', (2, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (2, -1), (-1, -1), 10),
        ('TEXTCOLOR', (3, -1), (3, -1), colors.HexColor('#15803d')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
    ]
    # Chargebacks in red
    if summary.get('chargebacks', 0) < 0:
        sum_style.append(('TEXTCOLOR', (3, 1), (3, 1), colors.HexColor('#dc2626')))
    # Bonus in purple
    if bonus_amt > 0:
        sum_style.append(('TEXTCOLOR', (3, -2), (3, -2), colors.HexColor('#7c3aed')))

    sum_table.setStyle(TableStyle(sum_style))
    story.append(sum_table)
    story.append(Spacer(1, 14))

    # ── Transaction Detail ────────────────────────────────────────
    story.append(Paragraph(f"Transaction Detail ({summary['total_lines']} lines)", styles['SectionHeader']))

    # Table header
    header = [
        Paragraph("<b>Policy #</b>", styles['TableCell']),
        Paragraph("<b>Insured</b>", styles['TableCell']),
        Paragraph("<b>Carrier</b>", styles['TableCell']),
        Paragraph("<b>Trans Type</b>", styles['TableCell']),
        Paragraph("<b>Premium</b>", styles['TableCellRight']),
        Paragraph("<b>Agent Comm</b>", styles['TableCellRight']),
        Paragraph("<b>Notes</b>", styles['TableCell']),
    ]

    table_data = [header]
    for item in sheet_data["line_items"]:
        notes = ""
        if item["is_chargeback"]:
            notes = "CHARGEBACK"

        row = [
            Paragraph(str(item["policy_number"])[:15], styles['TableCell']),
            Paragraph(str(item["insured_name"] or "—")[:20], styles['TableCell']),
            Paragraph(str(item["carrier"]).replace("_", " ")[:15], styles['TableCell']),
            Paragraph(str(item["transaction_type"])[:15], styles['TableCell']),
            Paragraph(fmt(item["premium"]), styles['TableCellRight']),
            Paragraph(fmt(item["agent_commission"]), styles['TableCellRight']),
            Paragraph(notes[:40], styles['TableCell']),
        ]
        table_data.append(row)

    col_widths = [1.1 * inch, 1.4 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch, 0.9 * inch, 2.7 * inch]
    detail_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # Style the detail table
    style_cmds = [
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#334155')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]

    # Highlight chargeback rows in red
    for i, item in enumerate(sheet_data["line_items"], start=1):
        if item["is_chargeback"]:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fef2f2')))
            style_cmds.append(('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#dc2626')))

    detail_table.setStyle(TableStyle(style_cmds))
    story.append(detail_table)

    # Footer
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cbd5e1')))
    story.append(Spacer(1, 4))
    from datetime import datetime
    story.append(Paragraph(
        f"Generated on {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')} — Better Choice Insurance",
        styles['SmallRight']
    ))

    doc.build(story)
    return buffer.getvalue()
