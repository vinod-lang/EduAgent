"""Content-equivalent in-memory renderers, independent of AI output parsing."""
import io
import os
from pathlib import Path
from document_models import DocumentError,CATALOG
from document_templates import get_template

class DocumentExportError(DocumentError): pass


def pdf_font(text):
    from fontTools.ttLib import TTFont
    override=os.environ.get('EDUAGENT_DOCUMENT_FONT')
    paths=[Path(override)] if override else [Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    for path in paths:
        if not path.is_file():continue
        try:
            with TTFont(path,lazy=True) as font:
                glyphs=font.getBestCmap() or {}
                if all(c.isspace() or ord(c) in glyphs for c in text):return str(path)
        except Exception:continue
    raise DocumentExportError('No local Unicode font covers this document. Set EDUAGENT_DOCUMENT_FONT to a suitable local TTF; no text was dropped.')


def visible_blocks(draft,template_id):
    blocks=get_template(template_id).blocks(draft)
    style=CATALOG[draft.document_type][1]
    for field,text in blocks:
        label={'subject':'Subject: ','reference_number':'Ref: '}.get(field,'')
        if style in ('email','memo'): label={'recipient':'To: ','sender':'From: '}.get(field,label)
        yield field,label+text


def document_docx_bytes(draft,template_id='standard_academic'):
    from docx import Document
    from docx.shared import Inches,Pt,RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    document=Document();template=get_template(template_id)
    section=document.sections[0]
    section.top_margin=section.bottom_margin=section.left_margin=section.right_margin=Inches(template.margin_inches)
    section.page_width=Inches(8.27);section.page_height=Inches(11.69)
    normal=document.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(11)
    normal.paragraph_format.space_after=Pt(9);normal.paragraph_format.line_spacing=1.15
    title_style=document.styles['Title']
    title_style.font.name='Arial';title_style.font.size=Pt(18);title_style.font.color.rgb=RGBColor(0,0,0)
    # Explicitly suppress inherited title borders in compatible viewers.
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    border=OxmlElement('w:pBdr')
    for edge in ('top','left','bottom','right','between'):
        item=OxmlElement('w:'+edge);item.set(qn('w:val'),'nil');border.append(item)
    title_style.element.get_or_add_pPr().append(border)
    for field,text in visible_blocks(draft,template_id):
        p=document.add_paragraph(text,'Title' if field=='title' else 'Normal')
        if field=='title':p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        if field in ('date','reference_number'):p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
        if field in ('subject','signature'):
            for run in p.runs:run.bold=True
        if field in ('title','subject','salutation','closing'):p.paragraph_format.keep_with_next=True
    buffer=io.BytesIO();document.save(buffer);return buffer.getvalue()


def document_pdf_bytes(draft,template_id='standard_academic'):
    from fpdf import FPDF
    blocks=tuple(visible_blocks(draft,template_id));font=pdf_font(''.join(t for _,t in blocks))
    pdf=FPDF();margin=get_template(template_id).margin_inches*25.4
    pdf.set_margins(margin,margin,margin);pdf.set_auto_page_break(True,margin=margin)
    try:
        pdf.add_font('Document',fname=font);pdf.add_page()
        pdf.set_title(draft.title or draft.subject);pdf.set_author('EduAgent')
        for field,text in blocks:
            pdf.set_x(pdf.l_margin);pdf.set_font('Document',size=17 if field=='title' else 11)
            if field in ('subject','salutation','closing') and pdf.get_y()>pdf.h-margin-25:pdf.add_page()
            pdf.multi_cell(0,6,text,align='C' if field=='title' else 'R' if field in ('date','reference_number') else 'L',new_x='LMARGIN',new_y='NEXT')
            pdf.ln(5 if field=='title' else 3)
        return bytes(pdf.output())
    except Exception as exc:raise DocumentExportError('Document PDF could not be formatted. Review unusually long content.') from exc
