"""Printable local HTML report; all user and provider strings are escaped."""
from html import escape

from .store import now


def report_html(analysis,history,comparison=None,model=None):
    esc=lambda value:escape(str(value if value is not None else ''),quote=True)
    snapshot=analysis['snapshot'];stats=analysis['stats']
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>链证 AI 演示与证据报告</title>',
           '<style>body{font:14px/1.9 "Microsoft YaHei",sans-serif;color:#243b46;max-width:1000px;margin:40px auto;padding:0 25px}h1,h2,h3{color:#173b37}h1{font-size:27px}h2{font-size:19px;margin-top:30px}h3{font-size:15px}table{width:100%;border-collapse:collapse;font-size:12px;margin:15px 0}th,td{border:1px solid #dce5e1;padding:10px;text-align:left;overflow-wrap:anywhere}th{background:#edf5f0}small{color:#7f948a}.question{border-top:1px solid #e0e8e3;padding-top:15px;margin-top:20px}p{white-space:pre-wrap;overflow-wrap:anywhere}blockquote{background:#f4f8f5;border-left:3px solid #a3c4b3;padding:10px;font-size:12px}@media print{body{margin:0;max-width:none}tr,.question{break-inside:avoid}@page{size:A4;margin:18mm}}</style>',
           '<h1>链证 AI 演示与证据报告</h1>',
           f'<p>项目：{esc(snapshot["project"])}　快照：{esc(snapshot["label"])}<br>生成时间：{esc(now())}<br>清单 SHA256：{esc(snapshot["hash"])}</p>',
           '<p>本报告记录所选清单、公告数据和实际问答。清单命中不等于运行时可利用，升级方案仍需构建与业务测试。演示业务拓扑和迁移检查样例为人为构造，公告记录保留真实来源。</p>',
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
            parts.append('<p>模型输入：'+esc(budget.get('input_bytes'))+' / '+esc(budget.get('limit_bytes'))+' UTF-8 字节（不是 token 数）；发送证据 '+esc(budget.get('evidence_count'))+' 条，其中前段摘取 '+esc(budget.get('truncated_evidence'))+' 条、未发送 '+esc(budget.get('omitted_evidence'))+' 条。完整原文仍保留在本地引用中。</p>')
        parts.append('<p>'+esc('\n'.join(answer['limits']))+'</p><table><tr><th>证据</th><th>版本</th><th>原文位置</th><th>来源</th></tr>')
        for cite in answer['citations']:
            parts.append('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in (cite['id'],cite['version'],cite['locator'],cite['url'] or '本地导入'))+'</tr>')
        parts.append('</table></section>')
    parts.append('<p><small>报告仅保存证据与调用元数据，不包含 API 密钥。引用编号和摘录存在性检查不能替代语义与业务审核。</small></p></html>')
    return ''.join(parts)
