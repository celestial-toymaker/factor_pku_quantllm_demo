"""Verify the publication copy without reopening market data or altering a freeze."""
from pathlib import Path
import hashlib
import json
from .common import digest
from .evaluate import validate_metrics


def _exposure_semantics(path):
    """Identity and citation fields may be redacted; all research facts remain."""
    obj = json.loads(Path(path).read_text())
    for row in obj['later_exposure']:
        row.pop('owner', None)
        row.pop('evidence', None)
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def _publication_proof(root):
    proof = json.loads((root / 'release/publication_derivation.json').read_text())
    frozen = json.loads((root / 'configs/protocol_freeze.json').read_text())
    assert proof['original_freeze_sha256'] == digest(root / 'configs/protocol_freeze.json'), 'Freeze changed'
    old = proof['original_module_sha256']
    reconstructed = hashlib.sha256(json.dumps(sorted(old.items())).encode()).hexdigest()
    assert reconstructed == frozen['code_hash'], 'Original module evidence does not match the research freeze'
    current = {p.name: digest(p) for p in sorted((root / 'src/factorlab').glob('*.py'))}
    assert set(current) == set(old), 'Module inventory changed'
    allowed = {'report.py', 'verify.py'}
    changed = {name for name in old if old[name] != current[name]}
    assert changed <= allowed, 'Scientific implementation changed'
    assert current == proof['publication_module_sha256'], 'Publication module hash mismatch'
    edited_docs = proof['edited_frozen_documents']
    assert set(edited_docs) == {'research/method.md', 'research/exposure_ledger.json'}, 'Unexpected frozen-document edit'
    for name, original_hash in frozen['files'].items():
        if name in edited_docs:
            evidence = edited_docs[name]
            assert evidence['original_sha256'] == original_hash, 'Original document hash mismatch'
            assert digest(root / name) == evidence['publication_sha256'], 'Publication document hash mismatch'
            if name == 'research/exposure_ledger.json':
                assert _exposure_semantics(root / name) == evidence['preserved_semantics_sha256'], 'Exposure facts changed'
        else:
            assert digest(root / name) == original_hash, 'Frozen input changed: ' + name
    archived = proof['edited_archival_documents']
    assert set(archived) == {'research/invalidated/v1/exposure_ledger.json'}, 'Unexpected archival edit'
    old_freeze = root / 'research/invalidated/v1/protocol_freeze.json'
    assert digest(old_freeze) == proof['archival_freeze_sha256'], 'Archival freeze changed'
    for name, evidence in archived.items():
        assert evidence['original_sha256'] == json.loads(old_freeze.read_text())['files']['research/exposure_ledger.json'], 'Original archival evidence mismatch'
        assert digest(root / name) == evidence['publication_sha256'], 'Archival document hash mismatch'
        assert _exposure_semantics(root / name) == evidence['preserved_semantics_sha256'], 'Archival exposure facts changed'
    assert digest(root / 'results/metrics.json') == proof['metrics_sha256'], 'Research metrics changed'
    finalist = json.loads((root / 'configs/finalist.json').read_text())
    checksum = finalist.pop('freeze_hash')
    assert hashlib.sha256(json.dumps(finalist, sort_keys=True).encode()).hexdigest() == checksum, 'Finalist record changed'
    assert finalist['code_hash'] == frozen['code_hash'], 'Finalist and protocol disagree'
    return {'original_freeze_verified': True, 'scientific_modules_unchanged': True,
            'presentation_modules_changed': sorted(changed), 'empirical_values_changed': False}


def verify(root):
    root = Path(root)
    errors, checked, proof = [], 0, None
    try:
        metrics = json.loads((root / 'results/metrics.json').read_text())
        validate_metrics(metrics)
        provenance = json.loads((root / 'results/report_provenance.json').read_text())
        assert provenance['metrics_sha256'] == digest(root / 'results/metrics.json'), 'Report metrics hash mismatch'
        assert metrics['research_outcome'] in (root / 'SUBMISSION.md').read_text(), 'Report outcome mismatch'
        if (root / 'configs/protocol_freeze.json').exists():
            if (root / 'release/publication_derivation.json').exists():
                proof = _publication_proof(root)
            else:
                from .protocol import check_protocol
                check_protocol(root)
        checksums = root / 'release/checksums.sha256'
        if checksums.exists():
            for line in checksums.read_text().splitlines():
                expected, name = line.split('  ', 1)
                assert (root / name).is_file() and digest(root / name) == expected, 'Checksum mismatch: ' + name
                checked += 1
    except Exception as exc:
        errors.append(str(exc))
    return {'ok': not errors, 'errors': errors, 'checksums_checked': checked,
            'final_labels_read': False, 'publication_derivation': proof}
