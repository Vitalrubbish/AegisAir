"""外置 ExFAT 分析视图不依赖符号链接，且不覆盖、核对内容哈希。"""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_corrected_certificate_inputs import copy_verified_trace


class CertificateInputTests(unittest.TestCase):
    def test_exact_copy_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.jsonl';target=root/'target.jsonl'
            raw=b'{"step":0}\n';source.write_bytes(raw)
            entry=dict(trajectory=str(source),trajectory_sha256=hashlib.sha256(raw).hexdigest())
            copy_verified_trace(entry,target)
            self.assertEqual(target.read_bytes(),raw)
            self.assertFalse(target.is_symlink())
            with self.assertRaises(FileExistsError):
                copy_verified_trace(entry,target)
            self.assertEqual(source.read_bytes(),raw)

    def test_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.jsonl';source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'不一致'):
                copy_verified_trace(dict(trajectory=str(source),trajectory_sha256=hashlib.sha256(b'old').hexdigest()),root/'target.jsonl')


if __name__=='__main__':
    unittest.main()
