"""Build a synthetic, reviewable fixture, separate from the product demo. No network."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def build():
    scenarios=[]
    specs=[('dev','harbor','ledger','receipt','granite'),('dev','forest','image','video','willow'),
           ('dev','orbit','queue','worker','quartz'),('test','delta','search','index','cobalt'),
           ('test','prairie','event','stream','maple'),('test','summit','cache','storage','silver')]
    topics=[('审批记录','升级前必须保存审批记录与变更单。'),
            ('回归测试','发布前必须执行回归测试并记录结果。'),
            ('回滚方案','上线前需要演练回滚方案并核对旧版本配置。'),
            ('灰度发布','灰度发布期间需要观察错误率并保留监控截图。'),
            ('数据备份','变更前必须完成数据备份并验证恢复流程。'),
            ('接口契约','接口契约需要核对字段类型与空值处理。'),
            ('导出快照','导出快照需要覆盖两条业务入口并比对结果。'),
            ('安全扫描','安全扫描记录需要注明扫描时间和规则版本。'),
            ('性能基线','性能基线需要记录响应时间与并发条件。'),
            ('权限审查','权限审查需要核对角色与资源授权范围。')]
    for index,(split,root,a,b,leaf) in enumerate(specs):
        sid=f'project-{root}'
        names={'root':root+'-app','a':a+'-adapter','b':b+'-adapter','x':leaf+'-core','y':leaf+'-core'}
        versions={'root':'1.0.0','a':'2.0.0','b':'3.0.0','x':'1.2.0','y':'1.3.0'}
        nodes=[{'id':ref,'name':name,'version':versions[ref]} for ref,name in names.items()]
        edges=[{'source':s,'target':t,'evidence_id':f'{sid}-edge-{s}-{t}'}
               for s,t in [('root','a'),('a','x'),('root','b'),('b','y')]]
        documents=[{'id':e['evidence_id'],'package':'fixture','title':'依赖清单声明',
                    'text':f"{names[e['source']]} @ {versions[e['source']]} 直接依赖 {names[e['target']]} @ {versions[e['target']]}。"}
                   for e in edges]
        for ref,topic,content in [('a','审批记录','升级前必须保存审批记录与变更单。'),
                                  ('b','回归测试','发布前必须执行回归测试并记录结果。'),
                                  ('x','性能基线','需要记录响应时间与并发条件。'),
                                  ('y','权限审查','需要核对角色与资源授权范围。')]:
            documents.append({'id':f'{sid}-doc-{ref}','package':'fixture','title':names[ref]+' '+topic,
                              'text':f"{names[ref]} @ {versions[ref]} {topic}：{content}"})
        edge=lambda s,t:f'{sid}-edge-{s}-{t}'
        cases=[('multi-hop',f"{names['root']} 引入 {names['x']} 的依赖路径？",[e['evidence_id'] for e in edges]),
               ('direct',f"{names['root']} 到 {names['a']} 的依赖路径？",[edge('root','a')]),
               ('direct',f"{names['root']} 到 {names['b']} 的依赖路径？",[edge('root','b')]),
               ('version-path',f"{names['root']} 引入 {names['x']} 1.2.0 的路径？",[edge('root','a'),edge('a','x')]),
               ('version-path',f"{names['root']} 引入 {names['y']} 1.3.0 的路径？",[edge('root','b'),edge('b','y')]),
               ('document',f"{names['a']} 的审批记录要求？",[f'{sid}-doc-a']),
               ('document',f"{names['b']} 的回归测试要求？",[f'{sid}-doc-b']),
               ('document',f"{names['x']} 性能基线有哪些要求？",[f'{sid}-doc-x']),
               ('unknown','未收录的 zephyrwidget 是否兼容？',[]),
               ('unknown','zqxv-unlisted 安装许可？',[])]
        questions=[{'id':f'{sid}-q{i+1}','category':category,'question':q,'relevant_ids':ids}
                   for i,(category,q,ids) in enumerate(cases)]
        # Rotate requirements across beginning/middle/end. Test projects have different names.
        paragraphs=[f'{names["root"]} 项目背景记录 {i}：本段说明例行维护安排，与具体发布验收无关。' for i in range(150)]
        excerpt_questions=[]
        for i,(topic,content) in enumerate(topics):
            quote=f'{names["root"]} {content}'
            paragraphs.insert((i*17+index*11)%len(paragraphs),quote)
            excerpt_questions.append({'id':f'{sid}-span-{i+1}','question':f'{names["root"]} 的{topic}要求是什么？',
                                      'expected_quote':quote})
        scenarios.append({'id':sid,'split':split,'graph':{'root':'root','nodes':nodes,'edges':edges},
                          'documents':documents,'questions':questions,'long_document':'\n'.join(paragraphs),
                          'excerpt_questions':excerpt_questions})
    return {'version':1,'kind':'synthetic-independent-fixture','human_reviewed':False,
            'note':'与演示清单分离；由程序按人工可读规则合成，尚未经独立专家标注。按项目划分 dev/test，模板仍有相似性。',
            'scenarios':scenarios}


if __name__=='__main__':
    output=ROOT/'evaluation/benchmark-fixture.json'
    output.write_text(json.dumps(build(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(output)
