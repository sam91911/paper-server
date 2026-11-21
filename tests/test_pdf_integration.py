"""Exercise Poppler and the real PDF import path with a generated PDF."""
import shutil
import tempfile
import unittest
from pathlib import Path

from paper_app import library, pdf


def fixture_pdf():
    stream = b'BT /F1 18 Tf 72 720 Td (Measured power was 12.5 mW.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream']
    output = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(output)
    output.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(output)


@unittest.skipUnless(shutil.which('pdftotext'), 'Poppler is not installed')
class PdfIntegrationTests(unittest.TestCase):
    def test_real_extract_and_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library.sqlite3'
            library.initialize(path)
            with library.connect(path) as db:
                db.execute("INSERT INTO accounts(username,password_hash,salt) VALUES ('owner',?,?)", (b'h', b's'))
            result = pdf.import_pdf(path, 'paper.pdf', fixture_pdf(), {'id': 1, 'role': 'user'}, 'owner')
            self.assertTrue(result['has_text'])
            self.assertEqual(result['metrics'], 1)
            with library.connect(path) as db:
                metric = db.execute('SELECT page,metric,value,unit FROM metrics').fetchone()
                self.assertEqual(tuple(metric), (1, 'power', '12.5', 'mW'))
                stored = db.execute('SELECT path FROM papers').fetchone()['path']
                self.assertEqual(Path(stored).read_bytes(), fixture_pdf())


if __name__ == '__main__':
    unittest.main()
