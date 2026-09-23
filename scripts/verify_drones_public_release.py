"""核验 Drones 公开包各 ZIP 成员与总包的 SHA-256。"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path


def digest(stream):
    value = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    args = parser.parse_args()
    root = args.release_dir
    expected = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        checksum, filename = line.split("  ", 1)
        expected[filename] = checksum
    for filename, checksum in expected.items():
        with (root / filename).open("rb") as stream:
            actual = digest(stream)
        if actual != checksum:
            raise ValueError(f"归档哈希不符: {filename}")
    manifest = json.loads((root / "file_manifest.json").read_text())
    entries = manifest["files"]
    counts = Counter()
    archives = sorted({entry["archive"] for entry in entries})
    for filename in archives:
        with zipfile.ZipFile(root / filename) as archive:
            in_archive = set(archive.namelist())
            claimed = [entry for entry in entries if entry["archive"] == filename]
            if in_archive != {entry["path"] for entry in claimed}:
                raise ValueError(f"成员清单不符: {filename}")
            for entry in claimed:
                with archive.open(entry["path"]) as stream:
                    if digest(stream) != entry["sha256"]:
                        raise ValueError(f"文件哈希不符: {entry['path']}")
                counts[entry["category"]] += 1
        print(f"{filename}: {len(claimed)} members verified", flush=True)
    print(f"PASS: {len(entries)} members; categories={dict(counts)}", flush=True)


if __name__ == "__main__":
    main()
