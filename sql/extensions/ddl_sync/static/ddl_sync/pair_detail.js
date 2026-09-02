/**
 * DDL 跨库同步 · 库对详情 JS
 *
 * ## CUSTOM-MODIFIED: v0.5.0-alpha pair_detail.js @ 2026-09-01 @ mavis
 * 设计参考: docs/designs/2026-09-01_ddl-sync-detail-ux-design.md §1
 *
 * 5 modal JS:
 * - 📥 批量导入 (R1)
 * - 🎯 一键配 (R2)
 * - + 添加同步表 (R1 兜底)
 * - 🔍 schema 差集 (Phase 2)
 * - ⚙️ 过滤规则 (Phase 3)
 *
 * 避坑 (8/13 AJAX 守卫 + 8/26 21:57 JS ReferenceError):
 * - 统一 handleAjaxError 处理 JSON 返 403 (W1-D4 §4.3 实战)
 * - 8/26 21:57 实战: 服务端返 data 已 json.dumps, 客户端不再用 |escapejs
 */

(function() {
  'use strict';

  // 1. 全局上下文
  const pairId = parseInt(window.location.pathname.split('/').filter(s => s).pop(), 10);
  // CUSTOM-MODIFIED: 修 D11 实战发现 CSRF 拿不到 @ 2026-09-02 @ mavis
  // 关联: docs/changelogs/2026-09-02_ddl-sync-w2-d11-csrf-fix.md
  // 修法: input[name=csrfmiddlewaretoken] 在没 form 页面找不到, fallback 从 csrftoken cookie 拿
  // 实战: Archery base.html 顶部没 form 包裹, 直接 querySelector 必 null
  const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
  const csrfCookie = document.cookie.match(/csrftoken=([^;]+)/);
  const csrfToken = (csrfInput && csrfInput.value)
                 || (csrfCookie && csrfCookie[1])
                 || '';
  const jsonHeaders = { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken };

  // 2. 统一错误处理 (W1-D4 §4.3)
  function handleAjaxError(xhr, defaultMsg) {
    let msg = defaultMsg;
    if (xhr.status === 403) {
      msg = '权限不足, 请联系 DBA 分配 ddl_sync 权限';
    } else if (xhr.status === 405) {
      msg = '方法不允许, 请刷新页面重试';
    } else if (xhr.status === 500) {
      msg = '服务异常, 请查看 gunicorn log';
    } else {
      try {
        const data = JSON.parse(xhr.responseText);
        if (data.error) msg = data.error;
        if (data.msg) msg = data.msg;
      } catch (e) {
        msg = '服务异常 (HTTP ' + xhr.status + ')';
      }
    }
    showToast(msg, 'error');
  }

  function showToast(msg, type) {
    // 简化 toast, 实际项目可换 Element UI notification
    if (type === 'error') {
      alert('❌ ' + msg);
    } else if (type === 'success') {
      alert('✅ ' + msg);
    } else {
      alert(msg);
    }
  }

  // 3. POST JSON 辅助
  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(body),
      credentials: 'same-origin',
    }).then(r => r.json().then(data => ({ status: r.status, data: data })));
  }

  // 4. 同步表 tab 搜索过滤 (D8 阶段 2 阶段 1 简单实现)
  function bindTableSearch() {
    const searchInput = document.getElementById('table-search');
    const filterSelect = document.getElementById('table-filter-sync-type');
    if (!searchInput || !filterSelect) return;
    const rows = document.querySelectorAll('#tab-tables tbody tr');
    function filter() {
      const keyword = searchInput.value.trim().toLowerCase();
      const syncType = filterSelect.value;
      rows.forEach(row => {
        const name = (row.dataset.tableName || '').toLowerCase();
        const type = row.dataset.syncType || '';
        const matchKeyword = !keyword || name.includes(keyword);
        const matchType = !syncType || type === syncType;
        row.style.display = (matchKeyword && matchType) ? '' : 'none';
      });
    }
    searchInput.addEventListener('input', filter);
    filterSelect.addEventListener('change', filter);
  }

  // ============== 5. R1 批量导入 modal ==============
  let bulkImportTables = [];
  let bulkImportSelected = new Set();

  function bindBulkImport() {
    const btn = document.getElementById('btn-bulk-import');
    if (!btn) return;
    btn.addEventListener('click', openBulkImportModal);

    document.getElementById('bulk-import-select-all').addEventListener('click', () => {
      bulkImportSelected = new Set(bulkImportTables.map(t => t.name));
      renderBulkImportTableList();
    });
    document.getElementById('bulk-import-deselect-all').addEventListener('click', () => {
      bulkImportSelected.clear();
      renderBulkImportTableList();
    });
    document.getElementById('bulk-import-search').addEventListener('input', () => {
      renderBulkImportTableList();
    });
    document.getElementById('bulk-import-table-all').addEventListener('change', e => {
      if (e.target.checked) {
        bulkImportSelected = new Set(bulkImportTables.map(t => t.name));
      } else {
        bulkImportSelected.clear();
      }
      renderBulkImportTableList();
    });
    document.getElementById('bulk-import-confirm').addEventListener('click', confirmBulkImport);
  }

  function openBulkImportModal() {
    // D8 阶段 2 阶段 1: modal 打开 + 模拟加载, 实际 1-click 用 compute_diff 扫源库 (D9 阶段 2 实战)
    // 这里简化: 从 DdlSyncPair 关联 tables 拿现有表名 + 提示用户走 🎯 一键配 拿全量
    const existingTables = new Set();
    document.querySelectorAll('#tab-tables tbody tr').forEach(row => {
      existingTables.add(row.dataset.tableName);
    });
    bulkImportTables = [];
    bulkImportSelected.clear();
    document.getElementById('bulk-import-result').style.display = 'block';
    document.getElementById('bulk-import-loading').style.display = 'none';
    showToast('批量导入 (D8 阶段 2 阶段 1 占位) - 实际请用 🎯 一键配 (覆盖配置) 走 1589 张表全量入库, 或 D9 阶段 2 实现的扫源库弹窗', 'info');
  }

  function renderBulkImportTableList() {
    const search = document.getElementById('bulk-import-search').value.trim().toLowerCase();
    const filtered = bulkImportTables.filter(t => !search || t.name.toLowerCase().includes(search));
    const tbody = document.getElementById('bulk-import-table-list');
    tbody.innerHTML = filtered.map(t => {
      const checked = bulkImportSelected.has(t.name) ? 'checked' : '';
      return '<tr>' +
        '<td><input type="checkbox" class="bulk-import-row" data-name="' + t.name + '" ' + checked + '></td>' +
        '<td><code>' + t.name + '</code></td>' +
        '<td>' + (t.exists ? '✓' : '—') + '</td>' +
        '<td>' + (t.size || '—') + '</td>' +
        '</tr>';
    }).join('');
    document.getElementById('bulk-import-total-count').textContent = filtered.length;
    document.getElementById('bulk-import-selected-count').textContent = bulkImportSelected.size;
    document.getElementById('bulk-import-preview-count').textContent = bulkImportSelected.size;
    document.getElementById('bulk-import-preview-count-2').textContent = bulkImportSelected.size;
    document.getElementById('bulk-import-confirm-count').textContent = bulkImportSelected.size;
    document.getElementById('bulk-import-confirm').disabled = bulkImportSelected.size === 0;
    // 复选框事件
    tbody.querySelectorAll('.bulk-import-row').forEach(cb => {
      cb.addEventListener('change', e => {
        const name = e.target.dataset.name;
        if (e.target.checked) bulkImportSelected.add(name);
        else bulkImportSelected.delete(name);
        document.getElementById('bulk-import-selected-count').textContent = bulkImportSelected.size;
        document.getElementById('bulk-import-preview-count').textContent = bulkImportSelected.size;
        document.getElementById('bulk-import-preview-count-2').textContent = bulkImportSelected.size;
        document.getElementById('bulk-import-confirm-count').textContent = bulkImportSelected.size;
        document.getElementById('bulk-import-confirm').disabled = bulkImportSelected.size === 0;
      });
    });
  }

  function confirmBulkImport() {
    if (bulkImportSelected.size === 0) return;
    const syncType = document.querySelector('input[name="bulk-import-sync-type"]:checked').value;
    postJSON('/ddl_sync/pair/' + pairId + '/bulk_import/', {
      table_names: Array.from(bulkImportSelected),
      sync_type: syncType,
    }).then(({ status, data }) => {
      if (status === 200 && data.ok) {
        showToast(data.msg, 'success');
        $('#modal-bulk-import').modal('hide');
        setTimeout(() => location.reload(), 1500);
      } else {
        showToast(data.error || '批量导入失败', 'error');
      }
    }).catch(xhr => handleAjaxError(xhr, '批量导入失败'));
  }

  // ============== 6. R2 一键配 modal ==============
  let oneClickData = { whitelist: [], blacklist: [], orphans: [] };
  let oneClickSelected = { whitelist: new Set(), blacklist: new Set() };

  function bindOneClickSetup() {
    const btn = document.getElementById('btn-one-click-setup');
    if (!btn) return;
    btn.addEventListener('click', openOneClickSetupModal);

    document.getElementById('one-click-whitelist-select-all').addEventListener('click', () => {
      oneClickSelected.whitelist = new Set(oneClickData.whitelist);
      updateOneClickPreview();
    });
    document.getElementById('one-click-whitelist-deselect-all').addEventListener('click', () => {
      oneClickSelected.whitelist.clear();
      updateOneClickPreview();
    });
    document.getElementById('one-click-blacklist-select-all').addEventListener('click', () => {
      oneClickSelected.blacklist = new Set(oneClickData.blacklist);
      updateOneClickPreview();
    });
    document.getElementById('one-click-blacklist-deselect-all').addEventListener('click', () => {
      oneClickSelected.blacklist.clear();
      updateOneClickPreview();
    });
    document.getElementById('one-click-whitelist-checkbox').addEventListener('change', e => {
      if (e.target.checked) oneClickSelected.whitelist = new Set(oneClickData.whitelist);
      else oneClickSelected.whitelist.clear();
      updateOneClickPreview();
    });
    document.getElementById('one-click-blacklist-checkbox').addEventListener('change', e => {
      if (e.target.checked) oneClickSelected.blacklist = new Set(oneClickData.blacklist);
      else oneClickSelected.blacklist.clear();
      updateOneClickPreview();
    });
    document.getElementById('one-click-confirm').addEventListener('click', confirmOneClickSetup);
  }

  function openOneClickSetupModal() {
    $('#modal-one-click-setup').modal('show');
    document.getElementById('one-click-loading').style.display = 'block';
    document.getElementById('one-click-result').style.display = 'none';
    document.getElementById('one-click-confirm').disabled = true;

    // 1) AJAX compute_diff
    postJSON('/ddl_sync/pair/' + pairId + '/compute_diff/', {})
      .then(({ status, data }) => {
        document.getElementById('one-click-loading').style.display = 'none';
        if (status === 200 && data.ok) {
          oneClickData = data.data;
          oneClickSelected.whitelist = new Set(oneClickData.whitelist);
          oneClickSelected.blacklist = new Set(oneClickData.blacklist);
          renderOneClickResult();
        } else {
          showToast(data.error || '差集计算失败', 'error');
          $('#modal-one-click-setup').modal('hide');
        }
      })
      .catch(xhr => {
        document.getElementById('one-click-loading').style.display = 'none';
        handleAjaxError(xhr, '差集计算失败');
        $('#modal-one-click-setup').modal('hide');
      });
  }

  function renderOneClickResult() {
    document.getElementById('one-click-source-count').textContent = oneClickData.whitelist.length + oneClickData.blacklist.length;
    document.getElementById('one-click-target-count').textContent = oneClickData.whitelist.length + oneClickData.orphans.length;
    document.getElementById('one-click-whitelist-count').textContent = oneClickData.whitelist.length;
    document.getElementById('one-click-blacklist-count').textContent = oneClickData.blacklist.length;
    document.getElementById('one-click-orphans-count').textContent = oneClickData.orphans.length;
    document.getElementById('one-click-result').style.display = 'block';
    updateOneClickPreview();
  }

  function updateOneClickPreview() {
    const w = oneClickSelected.whitelist.size;
    const b = oneClickSelected.blacklist.size;
    document.getElementById('one-click-preview-whitelist').textContent = w;
    document.getElementById('one-click-preview-blacklist').textContent = b;
    document.getElementById('one-click-preview-total').textContent = w + b;
    document.getElementById('one-click-confirm-count').textContent = w + b;
    document.getElementById('one-click-confirm').disabled = (w + b) === 0;
  }

  function confirmOneClickSetup() {
    const w = Array.from(oneClickSelected.whitelist);
    const b = Array.from(oneClickSelected.blacklist);
    if (w.length === 0 && b.length === 0) return;
    postJSON('/ddl_sync/pair/' + pairId + '/one_click_setup/', {
      accept_whitelist: w,
      accept_blacklist: b,
    }).then(({ status, data }) => {
      if (status === 200 && data.ok) {
        showToast(data.msg, 'success');
        $('#modal-one-click-setup').modal('hide');
        setTimeout(() => location.reload(), 1500);
      } else {
        showToast(data.error || '一键配失败', 'error');
      }
    }).catch(xhr => handleAjaxError(xhr, '一键配失败'));
  }

  // ============== 7. 单张加 modal ==============
  function bindAddTable() {
    const btn = document.getElementById('btn-add-table') || document.getElementById('btn-add-table-empty');
    if (!btn) return;
    btn.addEventListener('click', () => $('#modal-add-table').modal('show'));
    document.getElementById('add-table-confirm').addEventListener('click', confirmAddTable);
  }

  function confirmAddTable() {
    const tableName = document.getElementById('add-table-name').value.trim();
    if (!tableName) {
      showToast('表名不能为空', 'error');
      return;
    }
    const syncType = document.querySelector('input[name="add-table-sync-type"]:checked').value;
    const transformRuleStr = document.getElementById('add-table-transform-rule').value.trim();
    let transformRule = {};
    if (transformRuleStr) {
      try {
        transformRule = JSON.parse(transformRuleStr);
      } catch (e) {
        showToast('字段级规则 JSON 解析失败: ' + e.message, 'error');
        return;
      }
    }
    postJSON('/ddl_sync/pair/' + pairId + '/add_table/', {
      table_name: tableName,
      sync_type: syncType,
      transform_rule: transformRule,
    }).then(({ status, data }) => {
      if (status === 200 && data.ok) {
        showToast(data.msg, 'success');
        $('#modal-add-table').modal('hide');
        document.getElementById('add-table-name').value = '';
        document.getElementById('add-table-transform-rule').value = '';
        setTimeout(() => location.reload(), 1500);
      } else {
        showToast(data.error || '添加失败', 'error');
      }
    }).catch(xhr => handleAjaxError(xhr, '添加失败'));
  }

  // ============== 8. 初始化 ==============
  document.addEventListener('DOMContentLoaded', function() {
    bindTableSearch();
    bindBulkImport();
    bindOneClickSetup();
    bindAddTable();
  });
})();
