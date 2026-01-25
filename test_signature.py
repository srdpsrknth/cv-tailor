#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from renderers.docx_renderer import DocxRenderer
from models.tailored_output import TailoredCoverLetter
from models.profile import Profile

cl = TailoredCoverLetter(
    role_title='Product Manager',
    company_name='Tech Corp',
    paragraphs=['This is a test paragraph with closing signature.'],
    closing_line='Best regards,',
    signature_name='Alice Johnson'
)
p = Profile(version='1.0', identity={'full_name': 'Alice Johnson', 'email': 'alice@test.com', 'phone': '+1-555-9999'})
r = DocxRenderer()
docx, pdf = r.render_cover_letter(cl, p)
print(f'Generated: {Path(pdf).name}')
print(f'Size: {Path(pdf).stat().st_size} bytes')
is_valid = Path(pdf).read_bytes()[:4] == b'%PDF'
print(f'Valid PDF: {is_valid}')
