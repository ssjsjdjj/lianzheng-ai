"""Question-ranked literal excerpts. Offsets are Unicode code points, end exclusive."""
import math
import re
from collections import Counter


def words(text):
    result=re.findall(r'[a-z0-9_@./-]+',text.lower())
    for sequence in re.findall(r'[\u4e00-\u9fff]+',text):
        result.extend(sequence[i:i+2] for i in range(max(1,len(sequence)-1)))
    return result


def literal_spans(text,max_chars=200):
    spans=[]
    for match in re.finditer(r'[^\n。！？]+[。！？]?',text):
        if match.group().lstrip().startswith('#'):continue
        start,end=match.span()
        while start<end and text[start].isspace():start+=1
        while end>start and text[end-1].isspace():end-=1
        cursor=start
        while end-cursor>=8:
            stop=min(end,cursor+max_chars)
            spans.append({'start':cursor,'end':stop,'quote':text[cursor:stop]})
            if stop==end:break
            cursor=stop-40  # Preserve phrases straddling a long-line boundary.
    if not spans and len(text.strip())>=8:
        start=len(text)-len(text.lstrip())
        spans=[{'start':start,'end':min(len(text.rstrip()),start+max_chars),
                'quote':text[start:min(len(text.rstrip()),start+max_chars)]}]
    return spans


def ranked_spans(text,question):
    spans=literal_spans(text)
    query=set(words(question))
    bags=[set(words(span['quote'])) for span in spans]
    frequencies=Counter(t for bag in bags for t in bag)
    for span,bag in zip(spans,bags):
        span['score']=sum(1+math.log((len(spans)+1)/(frequencies[t]+1)) for t in query&bag)/math.sqrt(max(1,len(bag)))
    return sorted(spans,key=lambda s:(-s['score'],s['start']))


def select_excerpt(text,question,max_chars):
    if len(text)<=max_chars:return text,[]
    separator='\n[…]\n'
    selected=[];used=0;seen=set()
    for span in ranked_spans(text,question):
        if span['quote'] in seen:continue
        if any(span['start']<s['end'] and span['end']>s['start'] for s in selected):continue
        extra=len(span['quote'])+(len(separator) if selected else 0)
        if used+extra>max_chars:continue
        selected.append(span);seen.add(span['quote']);used+=extra
    if not selected:
        return text[:max_chars],[{'source_start':0,'source_end':max_chars,'text_start':0,'text_end':max_chars}]
    selected.sort(key=lambda s:s['start'])
    parts=[];ranges=[];position=0
    for span in selected:
        if parts:position+=len(separator)
        ranges.append({'source_start':span['start'],'source_end':span['end'],
                       'text_start':position,'text_end':position+len(span['quote'])})
        parts.append(span['quote']);position+=len(span['quote'])
    return separator.join(parts),ranges


def source_position(item,start,end):
    ranges=item.get('excerpt_ranges')
    if not ranges:return start,end
    for span in ranges:
        if span['text_start']<=start<end<=span['text_end']:
            offset=span['source_start']-span['text_start']
            return start+offset,end+offset
    return None  # A quote crossing an omission marker is not a literal source span.
