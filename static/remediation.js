(() => {
  'use strict';
  const panel = document.createElement('section');
  panel.id = 'remediation-panel';
  panel.className = 'panel remediation-panel';
  panel.setAttribute('aria-label', '修复任务工作台');
  panel.innerHTML = `<div class="panel-heading"><div><h2>修复任务工作台 <span class="count" id="task-count">0</span></h2><p>登记风险 → 记录处理 → 提交新清单复核</p></div><button class="text-button" type="button" id="refresh-tasks">刷新任务 ↻</button></div>
    <div class="task-intro"><strong>每条任务保留创建时的清单与公告依据。</strong><span>“清单复核通过”仅说明所选公告在完整清单和同一知识快照下无命中；构建、兼容性与上线仍需单独验证。</span></div>
    <form id="create-task-form" class="task-create-form"><div class="task-current-focus">当前公告 <output id="task-current-focus">尚未选择</output></div><div class="task-field-grid"><label>任务标题<input name="title" required maxlength="160" aria-label="新修复任务标题"></label><label>负责人<input name="owner" maxlength="100" placeholder="可稍后填写" aria-label="新修复任务负责人"></label></div><button class="button primary" type="submit" id="create-task" disabled>从当前风险建立任务</button><small>同一快照和公告重复点击会返回已有任务，不重复创建。</small></form>
    <p id="task-message" class="task-message" role="status" aria-live="polite"></p><div id="task-list" class="task-list" aria-busy="false"></div>`;
  document.getElementById('issues-panel').before(panel);
  const launch = document.createElement('button');
  launch.id = 'open-tasks'; launch.className = 'button secondary'; launch.type = 'button';
  launch.textContent = '修复任务';
  document.querySelector('.heading-actions').prepend(launch);
  launch.addEventListener('click', () => {
    changeView('overview'); panel.scrollIntoView({behavior: 'smooth', block: 'start'});
  });

  const find = selector => panel.querySelector(selector);
  const labels = {todo: '待处理', in_progress: '处理中', needs_review: '待复核', verified: '清单复核通过'};
  const eventLabels = {created: '建立任务', updated: '更新记录', verified: '清单复核通过', verification_failed: '复核未通过'};
  let scopeSerial = 0, listSerial = 0, currentSnapshot = null, tasks = [];
  const busyTokens = new WeakMap();
  const createForm = find('#create-task-form');
  function message(text, error = false) {
    find('#task-message').textContent = text;
    find('#task-message').classList.toggle('task-error', error);
  }
  function sameScope(snapshot, serial) { return snapshot === state.id && serial === scopeSerial; }
  async function act(button, label, action) {
    const snapshot = state.id, serial = scopeSerial, token = Symbol('task-action');
    busyTokens.set(button, token);
    const original = button.textContent;
    button.disabled = true; button.textContent = label;
    try { await action(); }
    catch (error) { if (button.isConnected && sameScope(snapshot, serial)) message(error.message || '任务操作失败，请稍后重试。', true); }
    finally {
      if (button.isConnected && busyTokens.get(button) === token) {
        button.disabled = button === find('#create-task') ? !state.analysis?.focus : false;
        button.textContent = original; busyTokens.delete(button);
      }
    }
  }

  function afterOptions(task) {
    return state.snapshots.filter(s => s.id !== task.snapshot_id && s.project === task.project &&
      new Date(s.created) >= new Date(task.source_snapshot.created));
  }
  function verificationHTML(task) {
    const result = task.verification;
    if (!result) return '<p class="task-empty-check">尚未提交修复后清单进行复核。</p>';
    const reasons = (result.reasons || []).map(r => `<li>${escapeHTML(r.message)}</li>`).join('');
    return `<div class="task-verification ${result.passed ? 'task-passed' : 'task-unconfirmed'}"><strong>${result.passed ? '该次清单复核通过' : '该次复核尚未通过'}</strong><p>${escapeHTML(result.after_snapshot.label)} · ${escapeHTML(dateLabel(result.created))}</p><p>${escapeHTML(result.note)}</p>${reasons ? '<ul>'+reasons+'</ul>' : ''}<p>剩余目标命中：${result.remaining_occurrences.length} 个位置 · 公告时间一致：${result.same_knowledge_snapshot ? '是' : '否'} · 对比覆盖完整：${result.comparison_complete ? '是' : '否'}</p><p class="task-freshness" data-task-freshness>正在核对当前证据是否仍与该次记录一致…</p></div>`;
  }
  function cardHTML(task) {
    const options = afterOptions(task);
    const afterID = task.verification?.after_snapshot?.id;
    const statusOptions = Object.entries(labels).map(([value, label]) =>
      `<option value="${value}" ${task.status === value ? 'selected' : ''} ${value === 'verified' ? 'disabled' : ''}>${label}</option>`).join('');
    const checks = task.checks.map(c => `<label><input type="checkbox" data-check="${escapeHTML(c.id)}" ${c.done ? 'checked' : ''}>${escapeHTML(c.label)}</label>`).join('');
    const occurrences = task.affected_occurrences.map(o => `<tr><td>${escapeHTML(o.package)}<br><small>${escapeHTML(o.version)}</small></td><td>${escapeHTML(o.ref)}<br><small>${escapeHTML(o.locator)}</small></td><td>${o.reachable ? '根节点可达' : '不可达 / 待核对'}</td></tr>`).join('');
    const paths = task.paths.map(p => `<li>${escapeHTML(p.label)}<small>${p.edges.map(e => escapeHTML(e.locator)).join('；')}</small></li>`).join('');
    const history = task.events.slice(-10).reverse().map(event => `<li><strong>${escapeHTML(eventLabels[event.type] || event.type)}</strong><time>${escapeHTML(dateLabel(event.created))}</time><details><summary>查看记录内容</summary><pre>${escapeHTML(JSON.stringify(event.details, null, 2))}</pre></details></li>`).join('');
    return `<article class="task-card" data-task-id="${escapeHTML(task.id)}"><div class="task-card-heading"><div><span class="task-focus">${escapeHTML(task.focus)}</span><h3>${escapeHTML(task.title)}</h3></div><span class="task-status task-status-${escapeHTML(task.status)}" data-task-status>${escapeHTML(labels[task.status] || task.status)}</span></div>
      <p class="task-summary">来源：${escapeHTML(task.source_snapshot.label)} · 已知受影响位置 ${task.affected_occurrences.length} 个 · 来源覆盖${task.coverage_complete ? '完整' : '不足'}</p>
      <p class="task-candidates">公告修复边界：${escapeHTML(task.candidate_versions.join('、') || '未声明')}<small>边界对应关系保留在任务导出的逐位置记录中；这些版本尚未证明业务兼容。</small></p>
      <details class="task-source"><summary>核对创建时的受影响位置与路径</summary><div class="task-table-wrap"><table><thead><tr><th>包与来源版本</th><th>出现位置 / 清单定位</th><th>路径状态</th></tr></thead><tbody>${occurrences}</tbody></table></div><ol class="task-paths">${paths}</ol>${task.paths_truncated ? '<p>这里只展示最多 5 条代表路径，受影响位置列表未按路径数量截断。</p>' : ''}</details>
      <form class="task-edit-form"><div class="task-field-grid"><label>任务标题<input name="title" required maxlength="160" value="${escapeHTML(task.title)}" aria-label="${escapeHTML(task.focus)} 任务标题"></label><label>负责人<input name="owner" maxlength="100" value="${escapeHTML(task.owner)}" aria-label="${escapeHTML(task.focus)} 负责人"></label><label>处理状态<select name="status" aria-label="${escapeHTML(task.focus)} 处理状态">${statusOptions}</select></label></div><fieldset class="task-checks"><legend>处理检查项 · 人工填写，不自动证明测试通过</legend>${checks}</fieldset><label class="task-note-label">添加处理备注<textarea name="note" rows="2" maxlength="2000" placeholder="例如：测试记录位置、剩余疑问或审批说明" aria-label="${escapeHTML(task.focus)} 处理备注"></textarea></label><div class="task-edit-actions"><button type="submit" class="button secondary">保存任务记录</button><a class="task-export" href="/api/tasks/${encodeURIComponent(task.id)}/report" download="remediation-${escapeHTML(task.id)}.json">导出任务 JSON ↓</a></div></form>
      <form class="task-verify-form"><label>修复后的实际清单<select name="after" required aria-label="${escapeHTML(task.focus)} 修复后快照"><option value="">请选择同项目的另一份快照</option>${options.map(s => `<option value="${escapeHTML(s.id)}" ${s.id === afterID ? 'selected' : ''}>${escapeHTML(s.label)} · ${escapeHTML(dateLabel(s.created))}</option>`).join('')}</select></label><button type="submit" class="button primary" ${options.length ? '' : 'disabled'}>提交清单复核</button><small>${options.length ? '只核对清单与公告证据，不会执行安装或业务测试。' : '请先导入同项目的修复后清单，再进行复核。'}</small></form>
      ${verificationHTML(task)}<details class="task-audit"><summary>审计记录 ${task.events.length} 条${task.events.length > 10 ? ' · 展示最近 10 条，导出可查看全部' : ''}</summary><ol>${history}</ol></details></article>`;
  }

  function renderTasks() {
    find('#task-count').textContent = tasks.length;
    find('#task-list').innerHTML = tasks.length ? tasks.map(cardHTML).join('') :
      '<div class="empty-state">当前快照还没有修复任务。<br>选择一个命中公告，从上方建立任务。</div>';
    for (const card of panel.querySelectorAll('[data-task-id]')) {
      const task = tasks.find(item => item.id === card.dataset.taskId);
      const edit = card.querySelector('.task-edit-form');
      edit.addEventListener('submit', event => {
        event.preventDefault();
        if (task.snapshot_id !== state.id || currentSnapshot !== state.id) return;
        const snapshot = state.id, serial = scopeSerial;
        const payload = {title: edit.elements.title.value.trim(), owner: edit.elements.owner.value.trim(),
          revision: task.revision ?? 1,
          checks: Object.fromEntries([...edit.querySelectorAll('[data-check]')].map(c => [c.dataset.check, c.checked]))};
        if (edit.elements.status.value !== task.status) payload.status = edit.elements.status.value;
        if (edit.elements.note.value.trim()) payload.note = edit.elements.note.value.trim();
        act(edit.querySelector('button[type=submit]'), '保存中…', async () => {
          await api('/api/tasks/'+encodeURIComponent(task.id), {method: 'PATCH', body: JSON.stringify(payload)});
          if (sameScope(snapshot, serial)) {await refreshTasks(); if (sameScope(snapshot, serial)) message('任务记录已保存。');}
        });
      });
      const verify = card.querySelector('.task-verify-form');
      verify.addEventListener('submit', event => {
        event.preventDefault();
        if (task.snapshot_id !== state.id || currentSnapshot !== state.id) return;
        const snapshot = state.id, serial = scopeSerial;
        const after = verify.elements.after.value;
        if (!after) return;
        act(verify.querySelector('button[type=submit]'), '正在复核…', async () => {
          const result = await api('/api/tasks/'+encodeURIComponent(task.id)+'/verify',
            {method: 'POST', body: JSON.stringify({after_snapshot_id: after, revision: task.revision ?? 1})});
          if (sameScope(snapshot, serial)) {
            await refreshTasks();
            if (sameScope(snapshot, serial)) message(result.verification?.passed ? '该次清单复核通过；业务测试与上线审批仍需单独完成。' : '尚不能确认目标公告已消除，具体原因已保存到任务。', !result.verification?.passed);
          }
        });
      });
    }
  }

  async function refreshTasks() {
    const snapshot = state.id, serial = ++listSerial, scope = scopeSerial;
    if (!snapshot || !state.analysis) return;
    find('#task-list').setAttribute('aria-busy', 'true');
    try {
      const result = await api('/api/snapshots/'+encodeURIComponent(snapshot)+'/tasks');
      if (!sameScope(snapshot, scope) || serial !== listSerial) return;
      tasks = result; renderTasks();
      // Reports compare stored fingerprints without rewriting past verification results.
      await Promise.all(tasks.filter(task => task.verification).map(async task => {
        try {
          const report = await api('/api/tasks/'+encodeURIComponent(task.id)+'/report');
          if (!sameScope(snapshot, scope) || serial !== listSerial) return;
          const card = [...panel.querySelectorAll('[data-task-id]')].find(c => c.dataset.taskId === task.id);
          if (!card) return;
          const freshness = card.querySelector('[data-task-freshness]');
          freshness.textContent = report.current_basis_matches === true ? '当前证据仍与该次复核记录一致。' :
            report.current_basis_matches === false ? '当前证据已变化，需要重新复核；上方保留的是历史结果。' : '当前证据一致性尚未确认。';
          freshness.classList.toggle('task-stale', report.current_basis_matches === false);
          if (report.current_basis_matches === false && task.status === 'verified') {
            const badge = card.querySelector('[data-task-status]');
            badge.textContent = '证据已变化 · 需重核'; badge.className = 'task-status task-status-needs_review';
          }
        } catch (error) {
          if (!sameScope(snapshot, scope) || serial !== listSerial) return;
          const card = [...panel.querySelectorAll('[data-task-id]')].find(c => c.dataset.taskId === task.id);
          if (card) card.querySelector('[data-task-freshness]').textContent = '暂时无法核对记录时效，请刷新任务后重试。';
        }
      }));
    } catch (error) {
      if (sameScope(snapshot, scope) && serial === listSerial) message(error.message || '修复任务暂时无法读取。', true);
    } finally {
      if (sameScope(snapshot, scope) && serial === listSerial) find('#task-list').setAttribute('aria-busy', 'false');
    }
  }

  function snapshotChanged() {
    ++scopeSerial; ++listSerial; tasks = [];
    currentSnapshot = state.id;
    find('#task-count').textContent = '0'; find('#task-list').innerHTML = '<p class="task-loading">正在读取当前快照的任务…</p>';
    const focus = state.analysis?.focus;
    find('#task-current-focus').textContent = focus || '尚未选择命中公告';
    createForm.elements.title.value = focus ? '复核并处理 '+focus : '';
    createForm.elements.owner.value = '';
    busyTokens.delete(find('#create-task'));
    find('#create-task').textContent = '从当前风险建立任务';
    find('#create-task').disabled = !focus;
    message(''); refreshTasks();
  }
  createForm.addEventListener('submit', event => {
    event.preventDefault();
    const snapshot = state.id, serial = scopeSerial, focus = state.analysis?.focus;
    if (!focus || currentSnapshot !== snapshot) return;
    const payload = {focus, title: createForm.elements.title.value.trim(), owner: createForm.elements.owner.value.trim()};
    act(find('#create-task'), '建立任务中…', async () => {
      await api('/api/snapshots/'+encodeURIComponent(snapshot)+'/tasks', {method: 'POST', body: JSON.stringify(payload)});
      if (sameScope(snapshot, serial)) {await refreshTasks(); if (sameScope(snapshot, serial)) message('任务已就绪，包含该公告的全部已知受影响位置。');}
    });
  });
  find('#refresh-tasks').addEventListener('click', () => refreshTasks());
  window.addEventListener('lianzheng-snapshot-changed', snapshotChanged);
  if (state.analysis) snapshotChanged();
})();
