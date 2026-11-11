'use strict';
// Link only server-provided node identities; never infer graph edges from model prose.
function answerPathDetails(answer){
  if(answer.mode==='text'||answer.facts?.snapshot_id!==state.id)return [];
  const nodes=new Map(state.analysis.nodes.map(n=>[n.id,n]));
  const edges=new Set(state.analysis.edges.map(e=>JSON.stringify([e.source,e.target])));
  const paths=answer.path_details||(answer.paths||[]).map((refs,i)=>{
    const label=refs.map(r=>{const n=nodes.get(r);return n?n.name+'@'+n.version:r;}).join(' → ');
    const citation=answer.citations?.find(c=>c.source==='graph-evidence'&&c.snapshot_id===answer.facts.snapshot_id&&c.text.split('\n')[0]===label);
    return {id:citation?.id||'history-path-'+i,nodes:refs,snapshot_id:answer.facts.snapshot_id,label};
  });
  return paths.filter(p=>p.snapshot_id===state.id&&p.nodes.length>1&&p.nodes.every(r=>nodes.has(r))&&
    p.nodes.slice(1).every((r,i)=>edges.has(JSON.stringify([p.nodes[i],r]))));
}

function showAnswerPath(answer,id){
  const path=answerPathDetails(answer).find(p=>p.id===id);
  if(!path){toast('该历史路径与当前快照不一致，请查看当时保存的证据。');return;}
  state.activePath=path;renderGraph();changeView('graph');
  $('#node-detail').textContent='当前高亮只对应这条引入路径；其他路径仍可能保留风险。';
}

function openAnswerEvidence(id,quote){
  const evidence=state.lastAnswer?.citations.find(c=>c.id===id);
  const card=document.getElementById('evidence-'+id);
  if(!evidence||!card)return;
  const details=card.querySelector('details'),body=details?.querySelector('p');
  if(!details||!body)return;
  $$('.evidence-card.evidence-selected').forEach(c=>c.classList.remove('evidence-selected'));
  $$('.evidence-card mark').forEach(mark=>mark.replaceWith(document.createTextNode(mark.textContent)));
  body.textContent=evidence.text;details.open=true;card.classList.add('evidence-selected');
  if(quote?.quote){
    let start=evidence.text.indexOf(quote.quote);
    if(Number.isInteger(quote.source_start)&&Number.isInteger(quote.source_end)){
      const codepoints=Array.from(evidence.text);
      if(codepoints.slice(quote.source_start,quote.source_end).join('')===quote.quote)
        start=codepoints.slice(0,quote.source_start).join('').length;
    }
    if(start>=0){
      const mark=document.createElement('mark');mark.textContent=quote.quote;
      body.replaceChildren(document.createTextNode(evidence.text.slice(0,start)),mark,
        document.createTextNode(evidence.text.slice(start+quote.quote.length)));
      mark.scrollIntoView({behavior:'smooth',block:'center'});
    }else card.scrollIntoView({behavior:'smooth',block:'center'});
  }else card.scrollIntoView({behavior:'smooth',block:'center'});
  card.setAttribute('tabindex','-1');card.focus({preventScroll:true});
}
