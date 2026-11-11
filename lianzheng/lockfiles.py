"""Read npm v2/v3 lockfiles without installing packages or contacting registries.

Only explicit node_modules locations are supported. Resolution follows the
ancestor node_modules search described by Node, bounded to this project. A
lockfile is supplied evidence, not proof of a runtime installation or semver
compatibility. Links and workspaces require a richer importer. Aliases need
both an explicit npm: declaration and a matching descriptor.name identity.
"""
import hashlib
import json
import re
from urllib.parse import quote

from .domain import InputError


MAX_PACKAGES=10_000  # Includes the project root, matching parse_bom's limit.
MAX_DECLARATIONS=50_000
MAX_INPUT_BYTES=5*1024*1024
MAX_LOCATION_DEPTH=30
ROOT_REF='npm:root'
_PART=re.compile(r'[A-Za-z0-9][A-Za-z0-9._~-]*\Z')
_SEMVER=re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
                   r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
                   r'(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z')
_SPEC=re.compile(r'[0-9A-Za-z.*^~<>=|+\- \t]+\Z')
_FIELDS=('dependencies','optionalDependencies','peerDependencies','devDependencies')


def _package_name(value):
    if not isinstance(value,str) or not 1<=len(value)<=214:return False
    pieces=value[1:].split('/') if value.startswith('@') else value.split('/')
    if len(pieces)!=(2 if value.startswith('@') else 1):return False
    return all(_PART.fullmatch(piece) and piece!='node_modules' for piece in pieces)


def _version(value):
    if not isinstance(value,str) or not 1<=len(value)<=100:return False
    match=_SEMVER.fullmatch(value)
    return bool(match and (not match.group(4) or all(not (p.isdigit() and len(p)>1 and p[0]=='0')
                                                   for p in match.group(4).split('.'))))


def _alias(spec):
    value=spec.strip()
    if not value.startswith('npm:'):return None
    target=value[4:]
    if '@' not in target[1:]:raise InputError('npm: 别名必须声明真实包名及版本范围，例如 npm:real-name@^1.0.0。')
    name,version=target.rsplit('@',1)
    if not _package_name(name) or not version.strip() or not _SPEC.fullmatch(version):
        raise InputError('npm: 别名的真实包名或版本范围无效。')
    return name


def _location_name(location):
    if not isinstance(location,str) or not location or len(location)>2048:
        raise InputError('锁文件安装位置必须是 1 至 2048 字符的相对路径。')
    parts=location.split('/');index=0;depth=0;name=None
    while index<len(parts):
        if parts[index]!='node_modules' or index+1>=len(parts):
            raise InputError('只支持 node_modules 安装位置；workspace、链接及非标准安装布局请导出 CycloneDX SBOM。')
        index+=1
        if parts[index].startswith('@'):
            if index+1>=len(parts):raise InputError('锁文件中的 scoped 包位置不完整。')
            name=parts[index]+'/'+parts[index+1];index+=2
        else:name=parts[index];index+=1
        if not _package_name(name):raise InputError('锁文件中的包名或安装路径无效；不允许路径穿越、绝对路径或反斜杠。')
        depth+=1
        if depth>MAX_LOCATION_DEPTH:raise InputError(f'锁文件安装位置最多 {MAX_LOCATION_DEPTH} 层。')
    return name


def _reference(location):
    return 'npm:'+location if location else ROOT_REF


def _pointer(location,field=None,name=None):
    escape=lambda value:value.replace('~','~0').replace('/','~1')
    result='/packages/'+escape(location)
    if field is not None:result+='/'+field
    if name is not None:result+='/'+escape(name)
    return result


def _resolve(location,name,packages,peer=False):
    # Peer dependencies must be beside or above the declaring package, never
    # guessed from a private node_modules directory inside that package.
    parts=location.split('/') if location else []
    start=len(parts)-1
    if peer and parts:
        start=max(i for i,p in enumerate(parts) if p=='node_modules')-1
    for end in range(start,-2,-1):
        if end>=0 and parts[end]=='node_modules':continue
        prefix='/'.join(parts[:end+1])
        candidate=(prefix+'/' if prefix else '')+'node_modules/'+name
        if candidate in packages:return candidate
    return None


def _read_dependency_map(descriptor,field):
    value=descriptor.get(field,{})
    if not isinstance(value,dict):raise InputError(f'{field} 必须是对象。')
    if len(value)>5000:raise InputError('单个包的依赖声明过多，最多支持 5000 项。')
    for name,spec in value.items():
        if not _package_name(name):raise InputError(f'{field} 含无效的 npm 包名。')
        if not isinstance(spec,str) or not 1<=len(spec)<=500:
            raise InputError('依赖版本声明必须是 1 至 500 字符的字符串。')
        if _alias(spec) is not None:continue
        if not _SPEC.fullmatch(spec) or not spec.strip():
            raise InputError('当前只支持 npm 版本范围或标签；file、git、URL、workspace 和 link 依赖请导出 CycloneDX SBOM。')
    return value


def _fingerprint(raw):
    digest=hashlib.sha256();size=0
    try:
        for part in json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).iterencode(raw):
            encoded=part.encode('utf-8');size+=len(encoded)
            if size>MAX_INPUT_BYTES:raise InputError('锁文件最多 5 MB。')
            digest.update(encoded)
    except (TypeError,ValueError,RecursionError,UnicodeError) as error:
        if isinstance(error,InputError):raise
        raise InputError('锁文件必须是有效、可序列化的 JSON 数据。') from None
    return digest.hexdigest()


def convert_package_lock(raw):
    """Return a deterministic CycloneDX 1.6 object or raise InputError.

    Missing required/optional/dev/peer records produce visible import warnings
    and an incomplete composition; they never produce invented graph edges.
    Detailed warnings and the original JSON pointers are preserved in properties.
    Legacy v2 ``dependencies`` is intentionally ignored in favor of ``packages``.
    """
    if not isinstance(raw,dict):raise InputError('package-lock.json 顶层必须是对象。')
    lock_version=raw.get('lockfileVersion')
    if type(lock_version) is not int or lock_version not in (2,3):
        raise InputError('目前支持 package-lock.json v2/v3；v1 或其他格式请用新版 npm 生成锁文件，或导出 CycloneDX SBOM。')
    packages=raw.get('packages')
    if not isinstance(packages,dict) or '' not in packages or not isinstance(packages[''],dict):
        raise InputError('锁文件必须包含 packages 对象及 packages[""] 项目根记录。')
    if not 1<=len(packages)<=MAX_PACKAGES:raise InputError(f'锁文件最多 {MAX_PACKAGES} 个安装位置（含根项目）。')
    fingerprint=_fingerprint(raw)
    root=packages['']
    if raw.get('workspaces') or root.get('workspaces'):
        raise InputError('当前不支持 workspace 锁文件；请导出包含实际依赖边的 CycloneDX SBOM。')
    root_name=root.get('name',raw.get('name'))
    if not isinstance(root_name,str) or not root_name.strip() or len(root_name)>214 or any(ord(c)<32 for c in root_name):
        raise InputError('锁文件需要有效的项目名称（最多 214 字符）。')
    if raw.get('name') and root.get('name') and raw['name']!=root['name']:
        raise InputError('锁文件顶层名称与根项目名称不一致。')
    root_version=root.get('version',raw.get('version',''))
    if not isinstance(root_version,str) or (root_version and not _version(root_version)):
        raise InputError('根项目版本必须是精确版本，或不填写版本。')
    if raw.get('version') and root.get('version') and raw['version']!=root['version']:
        raise InputError('锁文件顶层版本与根项目版本不一致。')
    maps={};components=[];warnings=[];declarations=0;warning_count=0;identities={};alias_locations=set()
    def warn(message):
        nonlocal warning_count
        warning_count+=1
        if len(warnings)<100:warnings.append(message)
    for location,descriptor in sorted(packages.items()):
        if not isinstance(location,str) or not isinstance(descriptor,dict):
            raise InputError('packages 必须将字符串安装位置映射到包信息对象。')
        for flag in ('link','dev','optional','devOptional','inBundle','hasShrinkwrap'):
            if flag in descriptor and type(descriptor[flag]) is not bool:raise InputError(f'{flag} 必须是布尔值。')
        if descriptor.get('link'):
            raise InputError('当前不支持 workspace 或 link 符号链接；请导出 CycloneDX SBOM。')
        maps[location]={field:_read_dependency_map(descriptor,field) for field in _FIELDS}
        declarations+=sum(len(value) for value in maps[location].values())
        if declarations>MAX_DECLARATIONS:raise InputError(f'锁文件最多 {MAX_DECLARATIONS} 项依赖声明。')
        peer_meta=descriptor.get('peerDependenciesMeta',{})
        if not isinstance(peer_meta,dict):raise InputError('peerDependenciesMeta 必须是对象。')
        for peer,value in peer_meta.items():
            if not _package_name(peer) or not isinstance(value,dict) or ('optional' in value and type(value['optional']) is not bool):
                raise InputError('peerDependenciesMeta 中 optional 必须是布尔值。')
        if not location:continue
        installed_name=_location_name(location)
        name=descriptor.get('name',installed_name)
        if not _package_name(name):raise InputError('安装记录中的真实包名称无效。')
        identities[location]=name
        if name!=installed_name:alias_locations.add(location)
        version=descriptor.get('version')
        if not _version(version):raise InputError('每个安装记录必须有精确 npm 版本；git、file、范围或缺失版本不能用于漏洞匹配。')
        resolved=descriptor.get('resolved')
        if resolved is not None and (not isinstance(resolved,str) or not (resolved.startswith(('https://','http://')) or resolved=='registry.npmjs.org')):
            raise InputError('当前不支持 git、file 或其他非 registry 安装来源；请导出 CycloneDX SBOM。')
        properties=[{'name':'lianzheng:npm:location','value':location},
                    {'name':'lianzheng:npm:source-pointer','value':_pointer(location)}]
        if name!=installed_name:
            properties.extend([{'name':'lianzheng:npm:alias','value':installed_name},
                               {'name':'lianzheng:npm:alias-target','value':name}])
        for flag in ('dev','optional','devOptional','inBundle'):
            properties.append({'name':'lianzheng:npm:'+flag,'value':str(descriptor.get(flag,False)).lower()})
        # Preserve declared relationship kinds, not just their flattened edges.
        properties.append({'name':'lianzheng:npm:dependency-declarations',
                           'value':json.dumps(maps[location],ensure_ascii=False,sort_keys=True)})
        components.append({'type':'library','bom-ref':_reference(location),'name':name,'version':version,
                           'purl':'pkg:npm/'+quote(name,safe='/')+'@'+quote(version,safe='.+-'),
                           'scope':'optional' if descriptor.get('optional') or descriptor.get('devOptional') else 'required',
                           'properties':properties})
        if descriptor.get('hasShrinkwrap'):
            warn(f'{location} 声明内含 shrinkwrap；本次仅使用当前锁文件列出的安装记录，未读取其内部清单。')
    dependencies=[];relationships=[];validated_alias_locations=set()
    for location in sorted(packages):
        descriptor=packages[location];fields=maps[location]
        # Dependency package devDependencies are not installed for consumers.
        applicable=('dependencies','optionalDependencies','peerDependencies')+ (('devDependencies',) if not location else ())
        targets=[]
        for field in applicable:
            for name,spec in sorted(fields[field].items()):
                if field=='dependencies' and name in fields['optionalDependencies']:continue
                if field=='devDependencies' and (name in fields['dependencies'] or name in fields['optionalDependencies']):continue
                target=_resolve(location,name,packages,peer=field=='peerDependencies')
                alias_target=_alias(spec)
                if target is not None:
                    identity=identities[target]
                    if alias_target is not None:
                        if packages[target].get('name')!=alias_target:
                            raise InputError('npm: 别名声明与安装记录的显式 name 不一致或缺失，不能推断真实包身份。')
                        validated_alias_locations.add(target)
                    elif identity!=name:
                        raise InputError('依赖声明缺少 npm: 别名信息，或同一安装位置的包身份存在冲突。')
                optional=field=='optionalDependencies' or (field=='peerDependencies' and descriptor.get('peerDependenciesMeta',{}).get(name,{}).get('optional',False))
                relation={'source':_reference(location),'dependency':name,'kind':field,'optional':optional,
                          'declared_spec':spec,'alias_target':alias_target,
                          'source_pointer':_pointer(location,field,name),'target':_reference(target) if target is not None else None}
                relationships.append(relation)
                if target is None:
                    label=location or '根项目'
                    suffix=' 可选项可能因安装选择而缺失，不能据此推断漏洞或安装失败。' if optional else ''
                    warn(f'{label} 的 {field} 声明 {name}，但缺少可定位的安装记录；未创建依赖边。'+suffix)
                elif _reference(target) not in targets:targets.append(_reference(target))
        dependencies.append({'ref':_reference(location),'dependsOn':targets})
    if alias_locations-validated_alias_locations:
        raise InputError('安装位置与真实包名称不同，但缺少可核对的 npm: 别名依赖声明；请导出 CycloneDX SBOM。')
    for component in components:
        location=component['bom-ref'][4:]
        if location in validated_alias_locations and location not in alias_locations:
            component['properties'].extend([{'name':'lianzheng:npm:alias','value':_location_name(location)},
                                            {'name':'lianzheng:npm:alias-target','value':component['name']}])
    metadata_properties=[{'name':'lianzheng:import:format','value':'npm-package-lock'},
                         {'name':'lianzheng:import:lockfile-version','value':str(lock_version)},
                         {'name':'lianzheng:import:sha256','value':fingerprint},
                         {'name':'lianzheng:import:note','value':'安装位置按锁文件解析；未运行安装脚本、未联网、未验证 semver 范围是否满足或运行时实际安装状态。'},
                         {'name':'lianzheng:import:relationships','value':json.dumps(relationships,ensure_ascii=False,sort_keys=True)},
                         {'name':'lianzheng:import:warning-count','value':str(warning_count)}]
    if warning_count>len(warnings):warnings.append(f'另有 {warning_count-len(warnings)} 条导入警告；仅展示前 100 条，完整关系状态保留在转换后的元数据中。')
    metadata_properties.extend({'name':'lianzheng:import:warning','value':warning} for warning in warnings)
    root_component={'type':'application','bom-ref':ROOT_REF,'name':root_name,'version':root_version,
                    'properties':[{'name':'lianzheng:npm:source-pointer','value':'/packages/'},
                                  {'name':'lianzheng:npm:dependency-declarations','value':json.dumps(maps[''],ensure_ascii=False,sort_keys=True)}]}
    output={'bomFormat':'CycloneDX','specVersion':'1.6','version':1,
            'metadata':{'component':root_component,'properties':metadata_properties},
            'components':sorted(components,key=lambda item:item['bom-ref']),'dependencies':dependencies}
    if warnings:output['compositions']=[{'aggregate':'incomplete'}]
    return output
