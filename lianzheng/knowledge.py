"""Snapshot-scoped, exact-version document ingestion with original line locators."""
import hashlib
import re
from urllib.parse import urlsplit

from .domain import InputError
from .store import now

VERSION = re.compile(r'^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$')


def chunk_lines(text, max_chars=1100):
    """Keep every character, even a single overlong line, with line/column spans."""
    chunks, pieces, size, start, end = [], [], 0, None, None
    heading='正文'

    def flush():
        nonlocal pieces,size,start,end
        if pieces:
            chunks.append({'text':''.join(pieces),'line_start':start[0],'column_start':start[1],
                           'line_end':end[0],'column_end':end[1],'heading':heading})
        pieces,size,start,end=[],0,None,None

    for line_no,line in enumerate(text.splitlines(keepends=True),1):
        if re.match(r'^#{1,6}\s+\S',line):
            flush()
            heading=line.strip().lstrip('#').strip()[:120]
        for offset in range(0,len(line),max_chars):
            piece=line[offset:offset+max_chars]
            if pieces and size+len(piece)>max_chars:
                flush()
            if start is None:start=(line_no,offset+1)
            pieces.append(piece);size+=len(piece);end=(line_no,offset+len(piece))
    flush()
    return chunks


def prepare_document(snapshot, graph, payload):
    title=payload['title'].strip()
    package=payload['package'].strip()
    version=payload['version'].strip()
    target=(payload.get('target_version') or '').strip() or None
    text=payload['text'].replace('\r\n','\n').replace('\r','\n').lstrip('\ufeff')
    url=(payload.get('url') or '').strip()
    kind=payload.get('kind','migration')
    if not title or not text.strip():
        raise InputError('文档标题和正文不能为空。')
    if '\x00' in text:
        raise InputError('文档包含二进制空字符，请上传 UTF-8 Markdown 或纯文本。')
    if kind not in ('migration','project'):
        raise InputError('文档类型只能为 migration 或 project。')
    if not VERSION.fullmatch(version) or (target and not VERSION.fullmatch(target)):
        raise InputError('文档必须绑定精确版本，不能填写版本范围。')
    identities={(n['package_name'],n['package_version']) for n in graph['nodes'] if n.get('package_name')}
    if (package,version) not in identities:
        raise InputError('绑定的包与版本不在当前快照中，请重新选择。')
    if url:
        try:
            parts=urlsplit(url)
            if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:
                raise ValueError('invalid source URL')
        except ValueError as error:
            raise InputError('来源链接必须是无账号密码的 HTTPS 地址；也可以留空。') from error
    identity='\0'.join((snapshot,title,package,version,target or '',kind,url,text))
    identifier='doc-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
    document={'id':identifier,'snapshot_id':snapshot,'title':title,'package':package,'version':version,
              'target_version':target,'kind':kind,'source':'user-document','url':url,
              'text':text,'hash':hashlib.sha256(text.encode()).hexdigest(),'created':now(),
              'trust':'用户导入；适用范围由导入者声明，内容真实性未自动验证。'}
    chunks=chunk_lines(text)
    if len(chunks)>300:
        raise InputError('文档分块超过 300 段，请拆分文档。')
    document['chunks']=[{
        **chunk,'id':f'{identifier}-{i+1}','document_id':identifier,'snapshot_id':snapshot,
        'title':title+' / '+chunk['heading'],'package':package,'version':version,
        'target_version':target,'kind':kind,'source':'user-document','url':url,
        'locator':f"第 {chunk['line_start']} 行第 {chunk['column_start']} 列至第 {chunk['line_end']} 行第 {chunk['column_end']} 列",
        'fetched_at':document['created'],'vulnerability':None,'ref':None,'trust':document['trust'],
        'hash':hashlib.sha256(chunk['text'].encode()).hexdigest()
    } for i,chunk in enumerate(chunks)]
    return document


def document_summary(document):
    return {key:value for key,value in document.items() if key not in ('text','chunks')} | {
        'chunk_count':len(document['chunks']),'character_count':len(document['text'])}
