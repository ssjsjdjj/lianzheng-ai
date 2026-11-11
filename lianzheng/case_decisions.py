"""Compare recorded dependency changes; never execute a proposed repair."""
import copy
import hashlib
import json
import re
from urllib.parse import quote

from .domain import InputError, reachable_nodes
from .osv import findings_for


PHASES=('before','partial','after')
LABELS={'before':'原始基线','partial':'方案 A · 只更新直接依赖','after':'方案 B · 继续更新测试工具并迁移断言'}


class CaseDecisions:
    """One report derives every number from one verified, immutable bundle read."""
    def __init__(self,real_case):
        self.real_case=real_case

    @staticmethod
    def _json(files,name):
        if name not in files.contents:raise InputError('方案资料缺少必需的证据文件。')
        try:return json.loads(files.contents[name])
        except (ValueError,UnicodeError):raise InputError('方案证据不是有效 JSON。')

    @staticmethod
    def _link(files,name):
        if not isinstance(name,str) or name not in files.contents:raise InputError('方案引用的文件不在已校验案例中。')
        return {'name':name,'sha256':hashlib.sha256(files.contents[name]).hexdigest(),
                'url':'/api/real-case/files/'+quote(name,safe='/')}

    def _test(self,test,files,lock_name):
        if not isinstance(test,dict):raise InputError('缺少实际测试记录。')
        log=self._link(files,test.get('log_file'));lock=self._link(files,lock_name)
        if test.get('log_sha256')!=log['sha256'] or test.get('lockfile_sha256')!=lock['sha256']:
            raise InputError('测试记录没有绑定当前锁文件或日志。')
        raw=files.contents[log['name']]
        for field,label in (('passing','passing'),('pending','pending'),('failing','failing')):
            count=test.get(field)
            if type(count) is not int or count<0:raise InputError('测试结果计数无效。')
            matches=re.findall(rb'\b(\d+) '+label.encode()+rb'\b',raw)
            actual=int(matches[-1]) if matches else 0
            if actual!=count:raise InputError('测试记录与原始日志摘要不一致。')
        if type(test.get('exit_code')) is not int or (test['failing']>0 and test['exit_code']==0):
            raise InputError('测试退出码与失败记录不一致。')
        return {**copy.deepcopy(test),'log':log,'recorded':True,'rerun':False}

    @staticmethod
    def _inventory(plan):
        graph=plan['graph'];reachable=reachable_nodes(graph['root'],graph['edges'])
        direct={e['target'] for e in graph['edges'] if e['source']==graph['root']}
        packages=plan['raw_lockfile']['packages'];result={}
        for node in graph['nodes']:
            if node['root']:continue
            location=node['id'][4:];raw=packages[location]
            result[node['id']]={'ref':node['id'],'name':node['name'],'version':node['version'],
                'location':location,'locator':'/packages/'+location.replace('~','~0').replace('/','~1'),
                'dependency_kind':'direct' if node['id'] in direct else 'transitive' if node['id'] in reachable else 'unknown',
                'reachable':node['id'] in reachable,'dev':raw.get('dev') is True,
                'optional':raw.get('optional') is True,'in_bundle':raw.get('inBundle') is True}
        return result

    @staticmethod
    def _advisories(plan):
        return {hit['id'] for node in plan['graph']['nodes'] if not node['root']
                for hit in findings_for(node,plan['scans'][node['id']])}

    def _compare(self,left,right,focus):
        before=self._inventory(left);after=self._inventory(right);rows=[]
        totals={'added':0,'removed':0,'updated':0,'version_changed':0,'identity_changed':0,
                'direct':0,'transitive':0,'unknown':0}
        fields=('name','version','dev','optional','in_bundle','dependency_kind')
        for ref in sorted(before.keys()|after.keys()):
            a,b=before.get(ref),after.get(ref)
            changes=[f for f in fields if a and b and a[f]!=b[f]]
            if a and b and not changes:continue
            kind='added' if a is None else 'removed' if b is None else 'updated'
            scope=(b or a)['dependency_kind'];totals[kind]+=1;totals[scope]+=1
            totals['version_changed']+=int('version' in changes)
            totals['identity_changed']+=int('name' in changes)
            rows.append({'ref':ref,'change':kind,'changed_fields':changes,'dependency_kind':scope,'before':a,'after':b})
        ids_a=self._advisories(left)-{focus};ids_b=self._advisories(right)-{focus}
        complete=left['graph']['complete'] and right['graph']['complete'] and not left['unknown'] and not right['unknown']
        root_a=left['raw_lockfile']['packages'][''];root_b=right['raw_lockfile']['packages'][''];declarations=[]
        for kind in ('dependencies','devDependencies','optionalDependencies','peerDependencies'):
            a,b=root_a.get(kind,{}),root_b.get(kind,{})
            for name in sorted(a.keys()|b.keys()):
                if a.get(name)!=b.get(name):declarations.append({'kind':kind,'name':name,'before':a.get(name),'after':b.get(name)})
        return {'from_phase':left['phase'],'to_phase':right['phase'],'from_label':LABELS[left['phase']],
                'to_label':LABELS[right['phase']],'counts':{**totals,'total_changed':len(rows)},'changes':rows,
                'root_declaration_changes':declarations,
                'target':{'advisory_id':focus,'before_count':left['target_count'],'after_count':right['target_count']},
                'other_advisories':{'new':sorted(ids_b-ids_a),'retained':sorted(ids_a&ids_b),
                                    'no_longer_observed':sorted(ids_a-ids_b)},
                'coverage':{'complete':complete,'from_graph_complete':left['graph']['complete'],
                            'to_graph_complete':right['graph']['complete'],
                            'from_unqueried':left['unknown'],'to_unqueried':right['unknown']},
                'definitions':{'changed':'按精确安装位置比较名称、版本、dev/optional/inBundle 标记和已知直接/间接分类；未计算文件字节改动行数。',
                    'direct':'当前侧有明确的根项目依赖边；删除项使用原始侧分类。',
                    'transitive':'当前已知图中从根可达但不是直接依赖；缺失边不会补造。',
                    'no_longer_observed':'仅表示固定查询与已列安装位置未再观察到该公告，不表示全部风险已消除。'}}

    def report(self,from_phase='before',to_phase='after'):
        if from_phase not in PHASES or to_phase not in PHASES:
            raise InputError('仅支持比较 before、partial、after 三份实际清单。')
        try:case,files,digest,_=self.real_case._bundle()
        except KeyError:return {'available':False,'kind':'recorded-experiment','note':'尚未安装真实案例资料。'}
        if (case['id']!='http-server-minimist' or case['target'].get('package')!='minimist'
                or case['target']['advisory_id']!='GHSA-xvch-5gv4-984h'):
            raise InputError('当前方案时间线仅支持固定的 http-server / minimist 实验。')
        plans=self.real_case._plans(case,files,digest);by_phase={p['phase']:p for p in plans}
        if set(by_phase)!=set(PHASES):raise InputError('方案比较需要完整的三阶段实际清单。')
        commands=self._json(files,'commands.json');migration=self._json(files,'migration-notes.json')
        if not isinstance(commands,dict) or not isinstance(migration,dict):raise InputError('方案过程资料格式无效。')
        tests={p:self._test(case.get('tests',{}).get(p),files,case[p+'_lockfile']) for p in PHASES}
        if case['source'].get('before_lockfile_sha256')!=tests['before']['lockfile_sha256']:
            raise InputError('原始锁文件与声明的上游来源哈希不一致。')
        failure=self._test(case.get('migration_failure'),files,case['after_lockfile'])
        recorded_runs=commands.get('test_runs',{})
        if any(recorded_runs.get(p)!=case['tests'][p] for p in PHASES) or recorded_runs.get('after_before_migration')!=case['migration_failure']:
            raise InputError('命令过程与案例测试记录不一致。')
        if not failure['failing'] or failure['exit_code']==0:raise InputError('迁移前的失败记录不可隐藏。')
        if tests['after'].get('modified_assertions')!=2:raise InputError('案例必须保留两条测试 API 迁移说明。')
        migrations={field:self._link(files,migration.get(field)) for field in ('before_file','after_file','patch_file')}
        updates=commands.get('installation_and_updates',[])
        if not isinstance(updates,list) or not all(isinstance(x,dict) for x in updates):raise InputError('实际升级命令格式无效。')
        def update_for(phase):
            sha=tests[phase]['lockfile_sha256']
            return [copy.deepcopy(x) for x in updates if x.get('lockfile_sha256')==sha]
        def event(identifier,title,phase,test=None,**extra):
            return {'id':identifier,'title':title,'phase':phase,'recorded':True,'rerun':False,
                    'started_at':test.get('started_at') if test else None,
                    'finished_at':test.get('finished_at') if test else None,'test':test,
                    'target_count':by_phase[phase]['target_count'],**extra}
        timeline=[
            event('baseline','固定上游源码与基线测试','before',tests['before']),
            event('direct-update','更新直接 minimist，仍有一个目标位置','partial',tests['partial'],updates=update_for('partial')),
            event('framework-failure','继续更新 tap 后，两条原断言失败','after',failure,updates=update_for('after')),
            event('assertion-migration','迁移两条字符串包含断言的 API','after',migration={**migration,'files':migrations},
                  time_note='实际编辑时刻未单独记录；这里只展示记录中的先后顺序。'),
            event('final-tests','迁移后再次执行测试','after',tests['after'])]
        summaries=[]
        for phase in PHASES:
            plan=by_phase[phase];inv=self._inventory(plan)
            hits=[{**inv[node['id']]} for node in plan['graph']['nodes'] if not node['root']
                  and any(h['id']==case['target']['advisory_id'] for h in findings_for(node,plan['scans'][node['id']]))]
            summaries.append({'id':phase,'label':LABELS[phase],'target_count':plan['target_count'],
                'target_occurrences':hits,'components':len(inv),'advisory_count':len(self._advisories(plan)),
                'graph_complete':plan['graph']['complete'],'unqueried':plan['unknown'],'issues':plan['graph']['issues'],
                'test':tests[phase],'lockfile':self._link(files,case[phase+'_lockfile']),
                'manifest':self._link(files,phase+'.package.json'),
                'note':{'before':'未修改的上游源码与锁文件。','partial':'真实更新直接依赖，测试工具中的旧 minimist 仍保留。',
                        'after':'真实更新测试工具并迁移两条断言 API；这是历史实验方案，tap 16 已停止维护。'}[phase]})
        comparisons=[self._compare(by_phase['before'],by_phase[p],case['target']['advisory_id']) for p in ('partial','after')]
        return {'available':True,'kind':'recorded-experiment','release':'0.8.0','id':case['id'],'title':case['title'],
                'source':copy.deepcopy(case['source']),'target':copy.deepcopy(case['target']),'bundle_sha256':digest,
                'plans':summaries,'baseline_comparisons':[{k:v for k,v in c.items() if k!='changes'} for c in comparisons],
                'selected_comparison':self._compare(by_phase[from_phase],by_phase[to_phase],case['target']['advisory_id']),
                'timeline':timeline,'files':[self._link(files,e['name'])|{'label':e.get('label',e['name'])} for e in case['files']],
                'limitations':copy.deepcopy(case.get('limitations',[])),
                'model_calls':0,'network_calls':0,'persisted':False,'upstream_tests_rerun':False,
                'note':'基于已校验的冻结实验材料比较实际方案；不会安装依赖、执行测试、调用模型或改写当前工作空间。'}
