"""Offline retrieval comparison and excerpt ablation; never calls a model or embedding API."""
import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from lianzheng.domain import representative_paths
from lianzheng.excerpts import literal_spans,select_excerpt
from lianzheng.retrieval import Retriever,quote_catalog,tokens


def tfidf_rank(question,documents):
    counts=[Counter(tokens(d['title']+'\n'+d['text'])) for d in documents]
    df=Counter(t for bag in counts for t in bag)
    idf={t:1+math.log((len(counts)+1)/(n+1)) for t,n in df.items()}
    query=Counter(tokens(question))
    q={t:n*idf[t] for t,n in query.items() if t in idf}
    norm=math.sqrt(sum(v*v for v in q.values()))
    scores=[]
    for d,bag in zip(documents,counts):
        vector={t:n*idf[t] for t,n in bag.items()}
        score=sum(v*vector.get(t,0) for t,v in q.items())/(norm*math.sqrt(sum(v*v for v in vector.values())) or 1)
        if score>0:scores.append((d['id'],score))
    return [i for i,_ in sorted(scores,key=lambda row:-row[1])]


def rank(question,scenario,method,k):
    documents=scenario['documents']
    if method=='tfidf-cosine':return tfidf_rank(question,documents)[:k]
    found,_,_=Retriever().retrieve(question,documents,limit=len(documents))
    lexical=[d['id'] for d in found]
    if method=='bm25':return lexical[:k]
    graph=scenario['graph'];root=next(n for n in graph['nodes'] if n['id']==graph['root'])
    promoted=[]
    # Explicit entity names and path intent only; labels/relevant_ids are never used here.
    if '路径' in question and root['name'] in question:
        versions=set(re.findall(r'\d+\.\d+\.\d+',question))
        targets=[n for n in graph['nodes'] if n['id']!=graph['root'] and n['name'] in question
                 and (not versions or n['version'] in versions)]
        edge_ids={(e['source'],e['target']):e['evidence_id'] for e in graph['edges']}
        for node in targets:
            for path in representative_paths(graph,node['id'])['paths']:
                promoted.extend(edge_ids[(s,t)] for s,t in zip(path,path[1:]))
    return list(dict.fromkeys(promoted+lexical))[:k]


def metrics(found,relevant,k):
    relevant=set(relevant);hits=len(set(found)&relevant)
    if not relevant:return {'recall_at_k':None,'precision_at_k':None,'mrr':None,'abstained':not found}
    return {'recall_at_k':hits/len(relevant),'precision_at_k':hits/k,
            'mrr':next((1/(i+1) for i,v in enumerate(found) if v in relevant),0),'abstained':None}


def aggregate(rows):
    result={'questions':len(rows)}
    for key in ('recall_at_k','precision_at_k','mrr','abstained','expected_quote_found'):
        values=[r[key] for r in rows if r.get(key) is not None]
        if values:result[key]=round(mean(values),4)
    if rows:result['mean_elapsed_ms']=round(mean(r['elapsed_ms'] for r in rows),3)
    return result


def run(fixture,split,k):
    data=json.loads(fixture.read_text(encoding='utf-8'));results=[]
    # Explicitly disable optional remote embeddings even if the caller configured them.
    with patch.dict(os.environ,{'LZ_EMBEDDING_BASE_URL':'','LZ_EMBEDDING_MODEL':''}):
        for scenario in data['scenarios']:
            if split!='all' and scenario['split']!=split:continue
            input_only={key:scenario[key] for key in ('graph','documents')}
            for case in scenario['questions']:
                for method in ('bm25','tfidf-cosine','bm25+graph-paths'):
                    start=time.perf_counter();found=rank(case['question'],input_only,method,k)
                    results.append({'task':'retrieval','split':scenario['split'],'method':method,**case,
                                    'retrieved_ids':found,**metrics(found,case['relevant_ids'],k),
                                    'elapsed_ms':round((time.perf_counter()-start)*1000,4)})
            for case in scenario['excerpt_questions']:
                source=scenario['long_document']
                for method in ('prefix-first4','question-ranked4'):
                    start=time.perf_counter()
                    if method=='prefix-first4':quotes=[s['quote'] for s in literal_spans(source[:4000])[:4]]
                    else:
                        text,ranges=select_excerpt(source,case['question'],4000)
                        quotes=[q['quote'] for q in quote_catalog([{'id':'doc','text':text,'excerpt_ranges':ranges}],case['question'])]
                    results.append({'task':'excerpt','split':scenario['split'],'method':method,**case,
                                    'selected_quotes':quotes,'expected_quote_found':case['expected_quote'] in quotes,
                                    'elapsed_ms':round((time.perf_counter()-start)*1000,4)})
    summaries=[]
    for split_ in sorted({r['split'] for r in results}):
        for method in dict.fromkeys(r['method'] for r in results):
            rows=[r for r in results if r['split']==split_ and r['method']==method]
            if rows:summaries.append({'split':split_,'method':method,**aggregate(rows)})
    return {'kind':'offline-retrieval-and-excerpt-comparison','fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),
            'k':k,'model_calls':0,'embedding_api_calls':0,'human_reviewed':data['human_reviewed'],
            'limitations':['合成数据按项目分组；模板相似，不能代表真实业务分布或独立专家评测。',
                            '三种检索使用相同清单边与文本。图增强复用项目路径遍历，但此实验不等于完整问答服务效果。',
                            'TF-IDF 是词项向量基线，不是语义 embedding；真实语义向量评测尚未运行。',
                            '只评证据检索和片段命中，不测答案正确率、语义支持率或幻觉率。',
                            'precision@k 分母固定为 k；空标注问题单独统计 abstained，不计入 recall/MRR。',
                            '延迟为本机单次测量，不代表线上 SLA；原文片段命中仅按预标注的完整句子判定。'],
            'summaries':summaries,'results':results}


def write_html(report,path):
    esc=lambda v:html.escape(str(v))
    keys=['split','method','questions','recall_at_k','precision_at_k','mrr','abstained','expected_quote_found','mean_elapsed_ms']
    rows=''.join('<tr>'+''.join('<td>'+esc(row.get(k,'—'))+'</td>' for k in keys)+'</tr>' for row in report['summaries'])
    failures=[r for r in report['results'] if r.get('expected_quote_found') is False or
              (r.get('recall_at_k') is not None and r['recall_at_k']<1) or r.get('abstained') is False]
    details=''.join('<details><summary>'+esc(f"{r['split']} · {r['id']} · {r['method']}")+ '</summary><pre>'+esc(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details>' for r in failures)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>链证 AI · 可复现评测</title><style>
    body{font:15px/1.65 system-ui,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#183d3b;background:#f5f8f7}h1{font-size:30px}table{border-collapse:collapse;background:white;width:100%;font-size:13px}td,th{text-align:left;padding:10px;border-bottom:1px solid #dce7e4}.table{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:18px}details{margin:10px 0}code{overflow-wrap:anywhere}.badge{background:#d5eee7;padding:8px 14px;display:inline-block;border-radius:6px}</style>
    <h1>链证 AI · 可复现离线评测</h1><p class="badge">零模型调用 · 原始结果与失败记录全部保留</p>'''
    page+='<ul>'+''.join('<li>'+esc(v)+'</li>' for v in report['limitations'])+'</ul>'
    page+='<p>固定样本 SHA-256：<code>'+report['fixture_sha256']+'</code></p><div class="table"><table><thead><tr>'+''.join('<th>'+k+'</th>' for k in keys)+'</tr></thead><tbody>'+rows+'</tbody></table></div>'
    page+='<p>recall_at_k：标注证据召回率；precision_at_k：前 k 项标注命中数 / k；mrr：首条标注证据排名倒数；abstained：无标注证据问题返回空结果的比例；expected_quote_found：目标原句进入候选片段的比例。所有数值均为本合成集结果。</p>'
    page+=f'<h2>未完全命中的运行记录（{len(failures)} 条）</h2>'+details+'</html>'
    path.write_text(page,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=ROOT/'evaluation/benchmark-fixture.json')
    parser.add_argument('--split',choices=['dev','test','all'],default='dev')
    parser.add_argument('--k',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/benchmark-results.json')
    args=parser.parse_args()
    if not 1<=args.k<=20:parser.error('--k must be 1..20')
    report=run(args.fixture,args.split,args.k)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_html(report,args.output.with_suffix('.html'))
    print(json.dumps(report['summaries'],ensure_ascii=False,indent=2))
