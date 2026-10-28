import json
from pathlib import Path

import httpx
import pytest

from lianzheng.service import Service
from lianzheng.retrieval import Retriever,model_explanation

ROOT=Path(__file__).resolve().parent.parent


def test_different_advisory_snapshots_do_not_prove_remediation(tmp_path):
    service=Service(tmp_path/'test.sqlite3',ROOT/'fixtures');service.seed()
    scans=service.store.scans('demo-resolved')
    for scan in scans.values():
        if scan['status']=='checked':scan['fetched_at']='2099-01-01T00:00:00+00:00'
    service.store.save_scans('demo-resolved',scans,[])
    comparison=service.compare('demo-before','demo-resolved')
    assert comparison['resolved']==[]
    assert comparison['not_observed'] and not comparison['same_knowledge_snapshot']


def test_embedding_failure_returns_bm25_and_warning(tmp_path,monkeypatch):
    service=Service(tmp_path/'test.sqlite3',ROOT/'fixtures');service.seed()
    monkeypatch.setenv('LZ_EMBEDDING_BASE_URL','https://provider.invalid/v1')
    monkeypatch.setenv('LZ_EMBEDDING_MODEL','test')
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda request:httpx.Response(503)),**kwargs))
    results,mode,warning=Retriever().retrieve('lodash',service.store.documents('demo-before'),focus='GHSA-29mw-wpgm-hmr9')
    assert results and mode=='bm25' and warning


def test_valid_provider_response_is_parsed(monkeypatch):
    monkeypatch.setenv('LZ_LLM_BASE_URL','https://provider.invalid/v1');monkeypatch.setenv('LZ_LLM_MODEL','test')
    original=httpx.Client
    payload={'choices':[{'message':{'content':json.dumps({'explanation':'请先核对清单，再执行构建测试。','evidence_ids':['e1']})}}]}
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload)),**kwargs))
    explanation,warning=model_explanation('why',{'facts':{},'evidence':[{'id':'e1'}]})
    assert explanation['evidence_ids']==['e1'] and warning is None
