"""Export only verified public case evidence and a read-only decision report."""
import hashlib
from io import BytesIO
import json
import zipfile

from .domain import InputError


def evidence_archive(real_case, decisions):
    case, files, digest, _ = real_case._bundle()
    report = decisions.report()
    if report.get('bundle_sha256') != digest:
        raise InputError('案例依据在导出期间变化，请重新读取后再试。')
    contents = {'case.json': files.manifest_bytes, **files.contents}
    if sum(map(len, contents.values())) > 32 * 1024 * 1024:
        raise InputError('案例证据包过大，暂不支持一次导出。')
    contents['decisions.json'] = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
    index = {
        'release': '0.10.0', 'kind': 'frozen-case-evidence', 'case_id': case['id'],
        'case_manifest_sha256': digest,
        'files': [{'name': name, 'sha256': hashlib.sha256(raw).hexdigest()}
                  for name, raw in sorted(contents.items())],
        'note': '保存的公开项目实验材料及其离线计算结果；导出未重跑上游测试、查询公告或调用模型。'
    }
    # Names originate from the validated case allowlist, not filesystem globs.
    if 'bundle-index.json' in contents or 'decisions.json' in files:
        raise InputError('案例文件名与导出保留文件冲突。')
    contents['bundle-index.json'] = json.dumps(index, ensure_ascii=False, indent=2).encode('utf-8')
    payload = BytesIO()
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(contents.items()):
            entry = zipfile.ZipInfo('lianzheng-case-evidence/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, raw)
    return payload.getvalue()
