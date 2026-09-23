"""Render one DOCX and derive its PDF with LibreOffice, so page checks agree."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from .db import rows, one, encode
from .engine import draft_sections, active_requirements, requirement_status


def render_input(db, bid):
    company = one(db, 'companies', bid['company_id'])
    return encode({'title': bid['title'], 'company': company['name'], 'sections': draft_sections(db, bid)})


@lru_cache(maxsize=12)
def render_proposal(payload: str, draft: bool = False):
    data = json.loads(payload)
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.8)
    section.left_margin = section.right_margin = Inches(0.85)
    style = doc.styles['Normal']
    style.font.name, style.font.size = 'Liberation Serif', Pt(11)
    style.paragraph_format.space_after = Pt(7)
    for name in ('Title', 'Heading 1', 'Heading 2'):
        doc.styles[name].font.name = 'Liberation Sans'
        doc.styles[name].font.color.rgb = RGBColor.from_string('172E46')
    if draft:
        section.header.paragraphs[0].text = 'DRAFT - NOT FOR SUBMISSION'
    doc.add_heading(data['company'], 0)
    doc.add_paragraph(data['title'], 'Subtitle')
    for item in data['sections']:
        doc.add_heading(item['title'], 2)
        for c in item['claims']:
            doc.add_paragraph(c['text'])
    footer = section.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run('Page ')
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    docx = io.BytesIO()
    doc.save(docx)
    binary = os.getenv('LIBREOFFICE_BIN') or shutil.which('soffice') or shutil.which('libreoffice')
    if not binary:
        raise RuntimeError('LibreOffice is required to verify DOCX/PDF page counts. Install it or set LIBREOFFICE_BIN.')
    with tempfile.TemporaryDirectory(prefix='bid-render-') as tmp:
        root = Path(tmp)
        (root / 'Proposal.docx').write_bytes(docx.getvalue())
        try:
            result = subprocess.run([binary, '-env:UserInstallation=' + (root / 'profile').as_uri(),
                '--headless', '--convert-to', 'pdf', '--outdir', str(root), str(root / 'Proposal.docx')],
                capture_output=True, timeout=60, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Document rendering exceeded 60 seconds. Final export stays blocked.') from exc
        output = root / 'Proposal.pdf'
        if result.returncode or not output.exists():
            raise RuntimeError('DOCX rendering failed. Check the LibreOffice installation.')
        pdf = output.read_bytes()
    count = len(PdfReader(io.BytesIO(pdf)).pages)
    return docx.getvalue(), pdf, count


def checklist_pdf(title, lines):
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles['Title']), Spacer(1, 16)]
    for line in lines:
        story.extend([Paragraph(escape(line), styles['BodyText']), Spacer(1, 9)])
    SimpleDocTemplate(output, pagesize=letter, leftMargin=54, rightMargin=54).build(story)
    return output.getvalue()


def package(db, bid, final, findings):
    docx, pdf, count = render_proposal(render_input(db, bid), draft=not final)
    reqs = active_requirements(db, bid['id'])
    wb = Workbook()
    sheet = wb.active
    sheet.title = 'Compliance matrix'
    sheet.append(['Requirement ID', 'Requirement', 'Type', 'Scope', 'Mandatory', 'Status', 'Source', 'Location', 'Source quote', 'Evidence IDs', 'Prior requirement'])
    manifest = {'bid_id': bid['id'], 'company_identity': one(db, 'companies', bid['company_id']),
                'revision': bid['revision'], 'final': final,
                'page_count': count, 'requirements': [], 'claims': [], 'documents': []}
    for r in reqs:
        status, evidence = requirement_status(db, bid, r)
        values = [r['id'], r['text'], r['kind'], r['scope'], bool(r['mandatory']), status,
                  r['document_name'], r['locator'], r['quote'], ', '.join(e['id'] for e in evidence), r['supersedes'] or '']
        # Force text cells. Source data must never become a spreadsheet formula.
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = 's'
        manifest['requirements'].append({**r, 'status': status, 'evidence': evidence})
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(color='FFFFFF', bold=True)
        cell.fill = PatternFill('solid', fgColor='172E46')
    for col in ('A','C','D','E','F','G','H','J','K'):
        sheet.column_dimensions[col].width = 24
    for col in ('B','I'):
        sheet.column_dimensions[col].width = 65
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
        sheet.row_dimensions[row[0].row].height = 65
    xlsx = io.BytesIO()
    wb.save(xlsx)
    c = json.loads(bid['controls'])
    lines = [('SUBMISSION READY' if final else 'DRAFT - NOT FOR SUBMISSION'),
        f"Bid: {bid['title']}", f"Revision: {bid['revision']}",
        f"Deadline: {c.get('deadline', 'Not confirmed')}",
        f"Submission method: {c.get('submission_method', 'Not confirmed')}",
        f"Proposal pages: {count}. Confirmed maximum: {c.get('page_limit', 'Not confirmed')}.",
        'Only submit files listed in submission-files.txt. Keep the compliance matrix and provenance manifest for internal review.',
        'The DOCX is editable. Any edit after export cancels the reviewed status. Re-audit the changed proposal before submission.',
        'The customer must send the package before the deadline. This application does not submit bids.']
    lines += [f"BLOCKER: {f['finding']}" for f in findings]
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('Proposal.docx', docx)
        z.writestr('Proposal.pdf', pdf)
        z.writestr('internal/Compliance-Matrix.xlsx', xlsx.getvalue())
        z.writestr('internal/Submission-Checklist.pdf', checklist_pdf('Submission checklist', lines))
        files = ['Proposal.pdf (or Proposal.docx if the solicitation requires Word; do not send both unless requested)']
        for d in rows(db, 'SELECT * FROM documents WHERE bid_id=? ORDER BY sequence,created_at', (bid['id'],)):
            manifest['documents'].append({k: d[k] for k in ('id','name','sha256','kind','sequence','acknowledged')})
            if d['kind'] == 'response_attachment':
                # IDs prevent collisions. Never use an untrusted path directly.
                name = f"original-attachments/{d['id']}-{d['name']}"
                z.writestr(name, d['content'])
                files.append(name)
        manifest['claims'] = draft_sections(db, bid)
        manifest['ledger'] = rows(db, 'SELECT * FROM requirements WHERE bid_id=? ORDER BY created_at', (bid['id'],))
        manifest['review_events'] = rows(db, 'SELECT * FROM review_events WHERE bid_id=? ORDER BY created_at', (bid['id'],))
        manifest['audit_runs'] = rows(db, 'SELECT * FROM audit_runs WHERE bid_id=? ORDER BY created_at', (bid['id'],))
        z.writestr('internal/Provenance.json', encode(manifest))
        z.writestr('submission-files.txt', '\n'.join(files))
    return out.getvalue()
