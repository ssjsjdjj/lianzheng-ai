"""Deterministic functional acceptance checks; not a research benchmark."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from lianzheng.service import Service
from lianzheng.store import now

TARGET='GHSA-29mw-wpgm-hmr9'


def run(output):
    results=[]
    with tempfile.TemporaryDirectory() as folder:
        service=Service(Path(folder)/'eval.sqlite3',ROOT/'fixtures');service.seed()
        migration={'title':'功能验收迁移说明','package':'lodash','version':'4.17.20',
                   'target_version':'4.18.1','kind':'migration','url':'',
                   'text':'# 导出快照校验\n升级后执行报表与导出入口的回归测试。\n'}
        def import_migration():
            service.import_document('demo-before',migration)
            return len(service.list_documents('demo-before'))==1
        def rescan_preserves_documents():
            service.scan('demo-before',live=False)
            return len(service.list_documents('demo-before'))==1
        checks=[
          ('双路径召回',lambda:len(service.ask('demo-before','这个漏洞从哪里进入？',TARGET)['paths'])==2),
          ('部分修复仅剩一条目标路径',lambda:len(service.ask('demo-partial','依赖路径？',TARGET)['paths'])==1),
          ('部分修复仍保留目标漏洞',lambda:TARGET in service.compare('demo-before','demo-partial')['remaining']),
          ('完整修复后目标公告消除',lambda:TARGET in service.compare('demo-before','demo-resolved')['resolved']),
          ('4.17.21 仍有其他已知记录',lambda:any(v['version']=='4.17.21' for v in service.analyze('demo-partial')['findings'])),
          ('问答附带原始公告证据',lambda:len(service.ask('demo-before','影响依据？',TARGET)['citations'])==2),
          ('未知漏洞保留未知',lambda:service.ask('demo-before','CVE-2099-999999 是否影响？',TARGET)['insufficient']),
          ('不把命中推断为可利用',lambda:service.ask('demo-before','这个漏洞可利用吗？',TARGET)['insufficient']),
          ('不保证升级兼容性',lambda:service.ask('demo-before','升级后兼容吗？',TARGET)['insufficient']),
          ('文本基线不提供图路径',lambda:not service.ask('demo-before','依赖路径？',TARGET,mode='text')['paths']),
          ('清单质量完整性',lambda:service.analyze('demo-before')['complete']),
          ('已修复快照未命中查询数据',lambda:service.analyze('demo-resolved')['stats']['vulnerabilities']==0),
          ('版本绑定文档导入',import_migration),
          ('迁移问答引用项目文档',lambda:any(c['source']=='user-document' for c in service.ask('demo-before','升级到 4.18.1 的迁移要求？',TARGET)['citations'])),
          ('目标版本不同时隔离文档',lambda:not any(c['source']=='user-document' for c in service.ask('demo-before','升级到 4.17.21 的迁移要求？',TARGET)['citations'])),
          ('重新扫描保留项目文档',rescan_preserves_documents),
        ]
        for name,check in checks:
            start=time.perf_counter()
            try:passed=bool(check());error=None
            except Exception as exc:passed=False;error=str(exc)
            results.append({'check':name,'passed':passed,'elapsed_ms':round((time.perf_counter()-start)*1000,2),'error':error})
    report={'kind':'functional-smoke-checks','generated_at':now(),
            'data_snapshot':service.osv.fixture['fetched_at'],'model_mode':'evidence-template; no external model called',
            'disclaimer':'仅为固定演示集的功能验收，不是独立测试集准确率，不证明 GraphRAG 优于文本 RAG。',
            'passed':sum(r['passed'] for r in results),'total':len(results),'results':results}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Functional checks: {report['passed']}/{report['total']}; report: {output}")
    return report['passed']==report['total']


if __name__=='__main__':
    output=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'evaluation/smoke-results.json'
    raise SystemExit(0 if run(output) else 1)
