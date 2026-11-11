"""Printable local HTML report; all user and provider strings are escaped."""
from html import escape

from .store import now


def _mapping(value):
    return value if isinstance(value,dict) else {}


def _records(value):
    return [item for item in value if isinstance(item,dict)] if isinstance(value,list) else []


def _review_report(parts,value,esc):
    parts.append('<h2>逐条结论的人工证据复核</h2><p>以下为本机使用者对结论支持范围的人工记录，不是自动真伪判定，也不代表独立专家审定。原句逐字匹配只说明引用存在，不能单独证明语义支持。</p>')
    records=_records(value)
    if not records:
        parts.append('<p>本报告未包含逐条人工复核记录。未记录不等于已经通过复核。</p>')
        return
    labels={'pending':'待人工复核','supported':'人工标记：支持','partial':'人工标记：部分支持',
            'insufficient':'人工标记：证据不足','conflict':'人工标记：来源冲突'}
    literal_labels={'matched':'原文逐字匹配通过','mismatch':'原文未全部匹配','no_quotes':'没有可逐字核对的摘录'}
    for record in records:
        parts.append('<section class="question"><h3>问答 '+esc(record.get('answer_id','未记录'))+'：'+esc(record.get('question','未提供问题文本'))+'</h3>')
        claims=_records(record.get('claims'))
        if not claims:parts.append('<p>这条记录没有可导出的逐条人工复核结果。</p>')
        for position,claim in enumerate(claims,1):
            review=_mapping(claim.get('review'));literal=_mapping(claim.get('literal_check'))
            status=review.get('status','pending')
            label=labels.get(status,'未识别的复核状态') if isinstance(status,str) else '未识别的复核状态'
            literal_status=literal.get('status')
            literal_label=literal_labels.get(literal_status,'未记录原文匹配结果') if isinstance(literal_status,str) else '未记录原文匹配结果'
            index=claim.get('claim_index')
            number=index+1 if type(index) is int and index>=0 else position
            parts.append('<div class="review-record"><h3>结论 '+esc(number)+' · '+esc(label)+'</h3><p>'+esc(claim.get('text','未提供结论文本'))+'</p>')
            parts.append('<p>原文核对：'+esc(literal_label)+'。支持范围备注：'+esc(review.get('note') or '未填写')+'<br>标注更新时间：'+esc(review.get('updated_at') or '未记录')+'</p>')
            for quote in _records(literal.get('quotes')):
                parts.append('<blockquote>'+esc(quote.get('quote','未提供摘录'))+'<br><small>证据 '+esc(quote.get('evidence_id','未记录'))+' · '+esc(quote.get('source_title',''))+' · '+esc(quote.get('source_locator',''))+'</small></blockquote>')
            stale=claim.get('stale_review_count')
            if type(stale) is int and stale>0:
                parts.append('<p>有 '+esc(stale)+' 份旧内容标注已隔离，不能套用为当前结论的复核结果。</p>')
            parts.append('</div>')
        parts.append('</section>')


def _task_report(parts,value,esc):
    parts.append('<h2>修复任务与清单复核</h2><p>“清单复核通过”只描述所选目标公告在当时清单与知识快照下的检查结果，不代表全部风险消除、业务测试通过、兼容性保证或可以上线。检查项是使用者自行勾选的记录，不替代测试证据。证据变化后需要重新复核。</p>')
    tasks=_records(value)
    if not tasks:
        parts.append('<p>本报告未包含修复任务记录。</p>')
        return
    labels={'todo':'待处理','in_progress':'处理中','needs_review':'待复核','verified':'已记录目标公告清单复核通过'}
    for task in tasks:
        source=_mapping(task.get('source_snapshot'));basis=_mapping(task.get('source_basis'))
        verification=_mapping(task.get('verification'))
        after=_mapping(verification.get('after_snapshot'))
        status=task.get('status')
        label=labels.get(status,'未记录或未识别的任务状态') if isinstance(status,str) else '未记录或未识别的任务状态'
        complete_receipt=all(verification.get(key) is True for key in
                             ('passed','source_unchanged','comparison_complete','same_knowledge_snapshot','resolved'))
        complete_receipt=bool(complete_receipt and after.get('id') and after.get('hash')
                              and not verification.get('not_observed')
                              and not _records(verification.get('remaining_occurrences'))
                              and not _records(verification.get('reasons')))
        if status=='verified' and not complete_receipt:
            label='状态记录为 verified，但复核凭据不完整；本报告不确认通过'
        parts.append('<section class="question"><h3>'+esc(task.get('title') or '未命名修复任务')+'</h3><table><tr><th>任务</th><th>目标公告</th><th>负责人</th><th>任务状态</th></tr>')
        parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in
                                  (task.get('id','未记录'),task.get('focus','未记录'),task.get('owner') or '未指定',label))+'</tr></table>')
        parts.append('<p>来源项目：'+esc(source.get('project') or task.get('project') or '未记录')+'<br>来源快照：'+esc(source.get('id') or task.get('snapshot_id') or '未记录')+' · '+esc(source.get('label',''))+'<br>来源清单 SHA256：'+esc(source.get('hash') or basis.get('snapshot_hash') or '未记录')+'</p>')
        candidates=task.get('candidate_versions')
        if isinstance(candidates,list) and candidates:
            parts.append('<p>公告中的候选修复边界：'+esc('、'.join(str(v) for v in candidates))+'。这不是依赖可解析或业务兼容性的承诺。</p>')
        checks=_records(task.get('checks'))
        if checks:
            parts.append('<h3>人工检查项</h3><ul>')
            for check in checks:
                checked='人工勾选已完成' if check.get('done') is True else '待完成' if check.get('done') is False else '状态未记录'
                parts.append('<li>'+esc(checked)+'：'+esc(check.get('label') or check.get('id') or '未命名检查项')+'</li>')
            parts.append('</ul>')
        else:parts.append('<p>未记录人工检查项。</p>')
        if verification:
            passed='通过（仅对应当时的目标公告与清单范围）' if complete_receipt else '未通过' if verification.get('passed') is False else '结果未确认，复核凭据不完整'
            parts.append('<h3>最近一次清单复核记录</h3><p>结果：'+esc(passed)+'<br>记录时间：'+esc(verification.get('created') or '未记录')+'<br>修复后快照：'+esc(after.get('id') or '未记录')+' · '+esc(after.get('label',''))+'<br>修复后清单 SHA256：'+esc(after.get('hash') or '未记录')+'</p>')
            if verification.get('not_observed') is True:
                parts.append('<p>目标公告仅为“未观察到”，不能据此记为已修复。</p>')
            reasons=_records(verification.get('reasons'))
            if reasons:
                parts.append('<ul>'+''.join('<li>'+esc(reason.get('message') or reason.get('code') or '未提供原因')+'</li>' for reason in reasons)+'</ul>')
            if verification.get('note'):parts.append('<p>复核说明：'+esc(verification['note'])+'</p>')
        else:parts.append('<p>尚无新清单复核记录。</p>')
        notes=[(event.get('created'),_mapping(event.get('details')).get('note')) for event in _records(task.get('events'))
               if _mapping(event.get('details')).get('note')]
        if notes:
            parts.append('<h3>最近人工备注（最多 3 条）</h3>')
            for stamp,note in notes[-3:]:parts.append('<p>'+esc(stamp or '未记录时间')+'：'+esc(note)+'</p>')
        parts.append('</section>')


def _real_case_report(parts,case,esc):
    case=_mapping(case)
    if not case.get('available'):return
    source=_mapping(case.get('source'));verification=_mapping(case.get('verification'))
    parts.extend(['<h2>真实项目修复实验 · 冻结记录</h2>',
                  '<p>'+esc(case.get('title'))+'<br>上游来源：'+esc(source.get('url'))+'<br>固定提交：'+esc(source.get('commit'))+'<br>许可证：'+esc(source.get('license'))+'<br>案例清单 SHA256：'+esc(case.get('bundle_sha256'))+'</p>',
                  '<p>'+esc(case.get('note'))+'</p>',
                  '<p>目标公告：'+esc(case.get('focus'))+'。冻结记录中的目标匹配位置：修复前 '+esc(verification.get('target_before_count','未知'))+'；仅直接依赖更新后 '+esc(verification.get('target_partial_count','未记录'))+'；最终依赖更新后 '+esc(verification.get('target_after_count','未知'))+'。</p>'])
    if verification.get('comparison_complete') is not True:
        parts.append('<p>案例清单存在结构缺失或未查询项，不能把已知位置的命中下降解释成完整风险已消除。</p>')
    if _mapping(case.get('current')).get('basis_matches_recorded') is False:
        parts.append('<p>当前工作空间的扫描依据已变化；上述冻结实验记录不能替代当前复核。</p>')
    tests=_mapping(case.get('tests'))
    for phase,label in [('before','修复前'),('partial','仅直接依赖更新后'),('after','最终依赖更新后')]:
        record=_mapping(tests.get(phase))
        if not record:continue
        parts.append('<h3>'+label+'的实际执行记录</h3><p>命令：'+esc(record.get('command'))+'<br>退出码：'+esc(record.get('exit_code','未提供'))+'<br>范围：'+esc(record.get('summary'))+'<br>日志：'+esc(record.get('log_file'))+'</p>')
    parts.append('<p>推演结果不写入本报告的实际扫描数据。测试命令成功仅覆盖其已执行范围，不代表生产兼容或全部业务测试通过。</p>')
    for note in case.get('limitations',[]) if isinstance(case.get('limitations'),list) else []:parts.append('<p>'+esc(note)+'</p>')


def report_html(analysis,history,comparison=None,model=None):
    esc=lambda value:escape(str(value if value is not None else ''),quote=True)
    snapshot=analysis['snapshot'];stats=analysis['stats']
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>链证 AI 演示与证据报告</title>',
           '<style>body{font:14px/1.9 "Microsoft YaHei",sans-serif;color:#243b46;max-width:1000px;margin:40px auto;padding:0 25px}h1,h2,h3{color:#173b37}h1{font-size:27px}h2{font-size:19px;margin-top:30px}h3{font-size:15px}table{width:100%;border-collapse:collapse;font-size:12px;margin:15px 0}th,td{border:1px solid #dce5e1;padding:10px;text-align:left;overflow-wrap:anywhere}th{background:#edf5f0}small{color:#7f948a}.question{border-top:1px solid #e0e8e3;padding-top:15px;margin-top:20px}p{white-space:pre-wrap;overflow-wrap:anywhere}blockquote{background:#f4f8f5;border-left:3px solid #a3c4b3;padding:10px;font-size:12px}@media print{body{margin:0;max-width:none}tr,.question{break-inside:avoid}@page{size:A4;margin:18mm}}</style>',
           '<h1>链证 AI 演示与证据报告</h1>',
           f'<p>项目：{esc(snapshot["project"])}　快照：{esc(snapshot["label"])}<br>生成时间：{esc(now())}<br>清单 SHA256：{esc(snapshot["hash"])}</p>',
           '<p>本报告记录所选清单、公告数据和实际问答。清单命中不等于运行时可利用，升级方案仍需构建与业务测试。'+('演示业务拓扑和迁移检查样例为人为构造，公告记录保留真实来源。' if snapshot.get('demo') else '该快照来自导入清单，分析范围受文件中的依赖关系和已保存的查询证据限制。')+'</p>',
           '<h2>分析范围</h2><table><tr><th>组件位置</th><th>匹配公告</th><th>受影响位置</th><th>未完成查询</th></tr>',
           f'<tr><td>{stats["components"]}</td><td>{stats["vulnerabilities"]}</td><td>{stats["affected_occurrences"]}</td><td>{stats["unknown"]}</td></tr></table>',
           f'<p>依赖结构完整：{esc(analysis["complete"])}。来源：{esc(", ".join(analysis["sources"]))}。</p>',
           '<h2>公告匹配结果</h2><table><tr><th>公告</th><th>组件与版本</th><th>位置</th><th>严重性</th><th>数据获取时间</th></tr>']
    for finding in analysis['findings']:
        parts.append('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in (finding['id'],finding['package']+'@'+finding['version'],finding['ref'],finding['severity'],finding['fetched_at']))+'</tr>')
    parts.append('</table>')
    if comparison:
        parts.append('<h2>修复前后对比</h2><table><tr><th>比较</th><th>已消除</th><th>仍保留</th><th>新增</th><th>仅未观察到</th></tr>')
        for label,result in comparison:
            parts.append('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in (label,', '.join(result['resolved']) or '无',', '.join(result['remaining']) or '无',', '.join(result['introduced']) or '无',', '.join(result['not_observed']) or '无'))+'</tr>')
        parts.append('</table>')
    accepted=[item for item in history if item['answer'].get('generation')=='model-assisted']
    parts.append(f'<h2>模型与问答记录</h2><p>本报告所含问答中，通过本机引用校验的模型回答：{len(accepted)} 次。此计数不是独立准确率评测。</p>')
    if model:
        parts.append('<p>模型配置状态：'+esc('已通过连接验证' if model.get('verified') else '尚未通过连接验证')+'；请求模型：'+esc(model.get('model'))+'。</p>')
    for item in reversed(history[:8]):
        answer=item['answer'];explanation=answer.get('model_explanation')
        parts.append('<section class="question"><h3>提问 '+esc(item['question'])+'</h3><p>'+esc(answer['conclusion'])+'</p>')
        if explanation:
            metadata=explanation.get('metadata',{})
            parts.append('<small>模型返回：'+esc(metadata.get('returned_model') or metadata.get('requested_model'))+'；耗时 '+esc(metadata.get('elapsed_ms'))+' ms；用量 '+esc(metadata.get('usage',{}).get('total_tokens','未提供'))+' tokens；请求 '+esc(metadata.get('request_id'))+'</small>')
            for claim in explanation.get('claims',[]):
                parts.append('<p>'+esc(claim['text'])+'</p>')
                for quote in claim['quotes']:parts.append('<blockquote>'+esc(quote['quote'])+'<br><small>证据 '+esc(quote['evidence_id'])+'</small></blockquote>')
        else:
            parts.append('<small>本轮使用本地证据解释，未记录通过校验的真实模型回答。</small>')
            metadata=answer.get('model_attempt') or {}
            if metadata.get('usage'):
                parts.append('<p>模型尝试未通过核验或未完整返回；已有用量 '+esc(metadata['usage'].get('total_tokens','未提供'))+' tokens，仍可能计费。</p>')
        if metadata:
            parts.append('<p>服务类型：'+esc(metadata.get('provider','未提供'))+'；API：'+esc(metadata.get('api_family','未提供'))+'。</p>')
            cost=metadata.get('cost_estimate')
            if isinstance(cost,dict) and isinstance(cost.get('amount'),(int,float)):
                parts.append('<p>本次公开单价估算：'+esc(cost.get('currency'))+' '+esc(cost['amount'])+'；单价核对日期 '+esc(cost.get('pricing_as_of'))+'，以服务商最终账单为准。</p>')
            elif metadata.get('transport')=='http-request':
                parts.append('<p>本次费用估算未提供；没有费用数值不代表免费。</p>')
        budget=answer.get('model_budget') or metadata.get('input_budget') or {}
        if budget:
            parts.append('<p>模型输入：'+esc(budget.get('input_bytes'))+' / '+esc(budget.get('limit_bytes'))+' UTF-8 字节（不是 token 数）；发送证据 '+esc(budget.get('evidence_count'))+' 条，其中节选 '+esc(budget.get('truncated_evidence'))+' 条、未发送 '+esc(budget.get('omitted_evidence'))+' 条。完整原文仍保留在本地引用中。</p>')
        parts.append('<p>'+esc('\n'.join(answer['limits']))+'</p><table><tr><th>证据</th><th>版本</th><th>原文位置</th><th>来源</th></tr>')
        for cite in answer['citations']:
            parts.append('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in (cite['id'],cite['version'],cite['locator'],cite['url'] or '本地导入'))+'</tr>')
        parts.append('</table></section>')
    _real_case_report(parts,analysis.get('real_case'),esc)
    _review_report(parts,analysis.get('claim_reviews'),esc)
    _task_report(parts,analysis.get('remediation_tasks'),esc)
    parts.append('<p><small>报告仅保存证据、调用元数据及本机人工处理记录，不包含模型配置或 API 密钥字段。引用编号和摘录存在性检查不能替代语义与业务审核。</small></p></html>')
    return ''.join(parts)
