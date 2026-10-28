"""Three real model calls against the running local app; never reads or prints keys."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent.parent


def run(base):
    with httpx.Client(base_url=base,timeout=90) as client:
        health=client.get('/api/health').json()
        if not health.get('llm_verified'):
            print('Model has not passed a real connection test. Open /?setup=model first.')
            return 2
        if health.get('model',{}).get('provider')!='deepseek' or health['model'].get('base_url') not in ('https://api.deepseek.com','https://api.deepseek.com/v1'):
            print('This acceptance script requires the official DeepSeek endpoint; test stubs are not accepted.')
            return 2
        prepared=client.post('/api/demo/prepare',json={});prepared.raise_for_status();demo=prepared.json()
        parent=None;results=[]
        for question in ['这个漏洞通过哪些路径进入项目？',
                         f"那升级到 {demo['target_version']} 时，迁移文档要求检查什么？",
                         '这些检查还应注意哪些证据缺项？']:
            response=client.post(f"/api/snapshots/{demo['initial']}/ask",json={
                'question':question,'focus':demo['focus'],'mode':'graph','use_model':True,'parent_id':parent})
            response.raise_for_status();answer=response.json();parent=answer['id']
            results.append({'question':question,'passed':answer['generation']=='model-assisted',
                            'generation':answer['generation'],'parent_id':answer['parent_id'],
                            'target_version':answer['facts']['target_version'],
                            'model_metadata':(answer.get('model_explanation') or {}).get('metadata'),
                            'claims':(answer.get('model_explanation') or {}).get('claims',[]),
                            'elapsed_ms':answer['elapsed_ms'],'limits':answer['limits']})
            print('Real model answer accepted:',results[-1]['passed'])
        report={'kind':'real-provider-acceptance','generated_at':datetime.now(timezone.utc).isoformat(),'provider':health['model']['provider'],
                'verification':health['model']['verification'],'passed':sum(r['passed'] for r in results),
                'total':len(results),'disclaimer':'真实接口及引用格式验收，不代表独立测试集准确率。','results':results}
        output=ROOT/'evaluation/live-model-results.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'evaluation/live-model-status.json').write_text(json.dumps({
            'generated_at':report['generated_at'],'provider':report['provider'],'connection_verified':True,
            'qa_verified':report['passed']==report['total'],'accepted_answers':report['passed'],
            'total_answers':report['total'],'report':'live-model-results.json',
            'note':'真实接口及引用验收；不代表独立准确率评测。'},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Report saved:',output)
        return 0 if report['passed']==report['total'] else 1


if __name__=='__main__':raise SystemExit(run(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765'))
