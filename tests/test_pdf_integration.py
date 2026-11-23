"""Exercise Poppler and the real PDF import path with a generated PDF."""
import shutil
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from paper_app import accounts, library, pdf
from test_skill_api import request


def fixture_pdf(text=b'Measured power was 12.5 mW.'):
    stream = b'BT /F1 18 Tf 72 720 Td (' + text + b') Tj ET'
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

    def test_keyword_import_and_redetection_preserve_metric_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library.sqlite3'
            library.initialize(path)
            with library.connect(path) as db:
                db.execute("INSERT INTO accounts(username,password_hash,salt) VALUES ('owner',?,?)", (b'h', b's'))
                token = accounts.start_session(db, 1, None)
            headers = {"Content-Type": "application/pdf", "X-Paper-Filename": "paper.pdf",
                       "X-Paper-Metric-Keywords": quote(json.dumps(["PSNR"]))}
            status, result = request(path, "/api/papers", cookie=token, headers=headers,
                                     binary=fixture_pdf(b'Decoder PSNR reached 32 dB. Measured power was 12.5 mW.'))
            self.assertEqual(status, 200, result)
            self.assertEqual(result["metrics"], 1)
            paper_id = result["paper_id"]
            metrics_url = f"/api/paper-metrics?paper_id={paper_id}"
            original = request(path, metrics_url, cookie=token)[1]["metrics"][0]
            self.assertEqual((original["metric"], original["value"], original["unit"]), ("psnr", "32", "dB"))
            remove = {"metric_id": original["id"], "revision": 1, "action": "remove", "reason": "False match."}
            self.assertEqual(request(path, "/api/paper-metrics", cookie=token, data=remove)[0], 200)
            # Another keyword can label the same source differently, but it stays removed.
            self.assertEqual(request(path, "/api/detect-paper-metrics", cookie=token,
                                     data={"paper_id": paper_id, "keywords": ["decoder"]}),
                             (200, {"metrics": 0, "has_text": True}))
            self.assertEqual(request(path, metrics_url, cookie=token)[1]["metrics"], [])
            self.assertEqual(request(path, "/api/detect-paper-metrics", cookie=token,
                                     data={"paper_id": paper_id, "keywords": ["power"]})[0], 200)
            self.assertEqual([row["metric"] for row in request(path, metrics_url, cookie=token)[1]["metrics"]], ["power"])


if __name__ == '__main__':
    unittest.main()
