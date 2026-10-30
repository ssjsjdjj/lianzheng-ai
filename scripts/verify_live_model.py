"""Three real model calls against the running local app; never reads or prints keys."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent.parent
OFFICIAL_ENDPOINTS={
    'openai':{'https://api.openai.com/v1'},
    'deepseek':{'https://api.deepseek.com','https://api.deepseek.com/v1'},
}


def official_metadata(metadata,provider):
    if not isinstance(metadata,dict) or metadata.get('provider')!=provider or metadata.get('transport')!='http-request':return False
    if provider=='openai' and metadata.get('api_family')!='responses':return False
    names=[metadata.get('requested_model',''),metadata.get('returned_model','')]
    return (all(isinstance(name,str) and name.strip() for name in names) and
            not any(term in name.lower() for name in names for term in ('stub','mock')))


def run(base):
    with httpx.Client(base_url=base,timeout=90) as client:
        response=client.get('/api/health');response.raise_for_status();health=response.json()
        model=health.get('model',{});provider=model.get('provider')
        if not health.get('llm_verified'):
            print('Awaiting local API credentials and a verified real connection. Open /?setup=model first; live acceptance has not run.')
            return 2
        if (provider not in OFFICIAL_ENDPOINTS or model.get('base_url') not in OFFICIAL_ENDPOINTS[provider]
                or not official_metadata(model.get('verification'),provider)):
            print('Live acceptance requires a verified official OpenAI or DeepSeek endpoint; local or compatible test stubs are not accepted.')
            return 2
        prepared=client.post('/api/demo/prepare',json={});prepared.raise_for_status();demo=prepared.json()
        parent=None;results=[]
        for question in ['这个漏洞通过哪些路径进入项目？',
                         f"那升级到 {demo['target_version']} 时，迁移文档要求检查什么？",
                         '这些检查还应注意哪些证据缺项？']:
            response=client.post(f"/api/snapshots/{demo['initial']}/ask",json={
                'question':question,'focus':demo['focus'],'mode':'graph','use_model':True,'parent_id':parent})
            response.raise_for_status();answer=response.json();parent=answer['id']
            explanation=answer.get('model_explanation') or {};metadata=explanation.get('metadata');claims=explanation.get('claims',[])
            accepted=(answer['generation']=='model-assisted' and official_metadata(metadata,provider) and
                      bool(claims) and all(isinstance(claim,dict) and claim.get('evidence_ids') and claim.get('quotes') for claim in claims))
            results.append({'question':question,'passed':bool(accepted),
                            'generation':answer['generation'],'parent_id':answer['parent_id'],
                            'target_version':answer['facts']['target_version'],
                            'model_metadata':metadata,'claims':claims,
                            'elapsed_ms':answer['elapsed_ms'],'limits':answer['limits']})
            print('Real model answer accepted:',results[-1]['passed'])
        report={'kind':'real-provider-acceptance','generated_at':datetime.now(timezone.utc).isoformat(),'provider':provider,
                'verification':health['model']['verification'],'passed':sum(r['passed'] for r in results),
                'total':len(results),'disclaimer':'真实接口及引用格式验收，不代表独立测试集准确率。','results':results}
        output=ROOT/'evaluation/live-model-results.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'evaluation/live-model-status.json').write_text(json.dumps({
            'generated_at':report['generated_at'],'provider':report['provider'],'connection_configured':True,'connection_verified':True,
            'qa_verified':report['passed']==report['total'],'accepted_answers':report['passed'],
            'total_answers':report['total'],'report':'live-model-results.json',
            'note':'真实接口及引用验收；不代表独立准确率评测。'},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Report saved:',output)
        return 0 if report['passed']==report['total'] else 1


if __name__=='__main__':raise SystemExit(run(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765'))
