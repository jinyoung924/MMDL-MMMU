"""Fetch pinned official Geometry3K archives, verifying Git blob identity.

Only train is eligible for candidates. Validation/test are protection-only inputs.
No extracted evaluation examples or answers are written to training records.
"""
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
REV = '99e6b5293c7bb4a5eaf2a370e6b213c79ab33ebb'
FILES = {
    'train.zip': (89114132, '13cd1f121923595efb04ab160185ab8255e8bd25'),
    'val.zip': (12486000, 'ba4b957be793c5356591de55f6d7d710f94d9d7b'),
    'test.zip': (25524601, 'cdf74f8d16e3450839553c70ef345f43e42ef7c5'),
}
CACHE = Path('/tmp/geometry3k_audit')


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    out = ROOT / 'data/geometry_stability'
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for name, (size, git_sha) in FILES.items():
        path = CACHE / name
        url = f'https://raw.githubusercontent.com/lupantech/InterGPS/{REV}/data/geometry3k/{name}'
        if not path.exists():
            tmp = path.with_suffix('.partial')
            with requests.get(url, stream=True, timeout=(20, 90)) as response:
                response.raise_for_status()
                count = 0
                with tmp.open('wb') as f:
                    for block in response.iter_content(1024 * 1024):
                        count += len(block)
                        if count > size:
                            raise ValueError('Unexpected archive size')
                        f.write(block)
            assert count == size, (name, count, size)
            tmp.replace(path)
        blob = path.read_bytes()
        assert len(blob) == size
        actual = hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + blob).hexdigest()
        assert actual == git_sha, (name, actual, git_sha)
        records.append({'path': name, 'url': url, 'bytes': size, 'git_blob_sha1': actual,
                        'sha256': hashlib.sha256(blob).hexdigest(),
                        'purpose': 'candidate_source' if name == 'train.zip' else 'protection_only'})
        print(json.dumps({'verified': name, 'bytes': size}), flush=True)
    lock = {'repository': 'https://github.com/lupantech/InterGPS', 'revision': REV,
            'source': 'Official Geometry3K original split archives', 'files': records,
            'candidate_allowed_source_split': 'train', 'ready_for_training': False}
    target = out / 'source_lock.json'
    if target.exists():
        assert json.loads(target.read_text()) == lock, 'Source lock differs'
    else:
        target.write_text(json.dumps(lock, indent=2) + '\n')


if __name__ == '__main__':
    main()
