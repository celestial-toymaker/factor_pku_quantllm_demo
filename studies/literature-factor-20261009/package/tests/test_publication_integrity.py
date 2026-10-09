"""The publication copy must reject changes to frozen scientific evidence."""
import json
import hashlib
from pathlib import Path
import shutil
import pytest
from factorlab.verify import _publication_proof
from factorlab.protocol import check_finalist, ProtocolError


@pytest.fixture
def published_copy(tmp_path):
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / 'configs/protocol_freeze.json').read_text())
    files = set(frozen['files']) | {'configs/protocol_freeze.json', 'configs/finalist.json',
                                   'release/publication_derivation.json', 'results/metrics.json',
                                   'research/invalidated/v1/protocol_freeze.json',
                                   'research/invalidated/v1/exposure_ledger.json'}
    files |= {p.relative_to(root).as_posix() for p in (root / 'src/factorlab').glob('*.py')}
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    assert _publication_proof(tmp_path)['scientific_modules_unchanged']
    return tmp_path


@pytest.mark.parametrize('relative_path', [
    'src/factorlab/features.py', 'research/method.md', 'results/metrics.json',
    'research/exposure_ledger.json', 'research/invalidated/v1/exposure_ledger.json'
])
def test_modified_science_document_or_metrics_is_rejected(published_copy, relative_path):
    path = published_copy / relative_path
    path.write_bytes(path.read_bytes() + b'\n ')
    with pytest.raises(AssertionError):
        _publication_proof(published_copy)


def test_rewritten_original_module_evidence_is_rejected(published_copy):
    path = published_copy / 'release/publication_derivation.json'
    evidence = json.loads(path.read_text())
    evidence['original_module_sha256']['features.py'] = '0' * 64
    path.write_text(json.dumps(evidence))
    with pytest.raises(AssertionError, match='research freeze'):
        _publication_proof(published_copy)


def test_presentation_copy_does_not_reopen_original_finalist(published_copy):
    with pytest.raises(ProtocolError, match='Frozen data/config/code changed'):
        check_finalist(published_copy)


def test_redaction_cannot_change_exposure_dates(published_copy):
    name = 'research/exposure_ledger.json'
    path = published_copy / name
    obj = json.loads(path.read_text())
    obj['later_exposure'][1]['period'] = 'unexposed'
    path.write_text(json.dumps(obj))
    proof_path = published_copy / 'release/publication_derivation.json'
    proof = json.loads(proof_path.read_text())
    proof['edited_frozen_documents'][name]['publication_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    proof_path.write_text(json.dumps(proof))
    with pytest.raises(AssertionError, match='Exposure facts changed'):
        _publication_proof(published_copy)
