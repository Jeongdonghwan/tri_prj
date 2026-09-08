// 캠페인 관리: 행 클릭 → 순위 추적 모달, 등록/수정 모달, 체크박스 일괄 등록. (?open= 딥링크)
(function () {
  var rm = document.getElementById('rankModal'), rb = document.getElementById('rankBody');
  function closeRanks() { rm.classList.remove('on'); }
  function openRanks(id) {
    fetch(window.RANKS_BASE + id + '/ranks').then(function (r) { return r.text(); }).then(function (html) {
      rb.innerHTML = html;
      rm.classList.add('on');
      var x = document.getElementById('rkclose');
      if (x) x.addEventListener('click', closeRanks);
      if (window.lucide) window.lucide.createIcons();
    });
  }
  rm.addEventListener('click', function (e) { if (e.target === rm) closeRanks(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeRanks(); });

  // 행 클릭 → 순위 추적 화면 (등록 대기 슬롯은 등록 모달)
  document.querySelectorAll('tr[data-open]').forEach(function (tr) {
    tr.addEventListener('click', function (e) {
      if (e.target.closest('.rowact') || e.target.closest('a,button,form,input')) return;
      var fill = document.getElementById('fill' + tr.dataset.open);
      var isPending = tr.querySelector('.st') && tr.querySelector('.st').classList.contains('s-wait');
      if (isPending && fill) { fill.classList.add('on'); return; }
      openRanks(tr.dataset.open);
    });
  });

  // URL 즉시 검증 (모달 안에서 안내, 잘못되면 제출 막음) — 네이버 쇼핑/스토어 도메인만
  var URL_OK = /(^|\.)(smartstore|brand|shopping)\.naver\.com/i;
  document.querySelectorAll('form[action$="/fill"], form[action$="/bulk-fill"]').forEach(function (f) {
    var input = f.querySelector('input[name="target_url"]');
    if (!input) return;
    var hint = document.createElement('div');
    hint.style.cssText = 'color:var(--danger);font-size:12px;margin-top:4px;display:none';
    input.parentNode.appendChild(hint);
    f.addEventListener('submit', function (e) {
      var v = (input.value || '').trim().replace(/^https?:\/\//i, '');
      if (!URL_OK.test(v)) {
        e.preventDefault();
        hint.textContent = '스마트스토어 · 브랜드스토어 · 쇼핑 주소만 등록할 수 있어요. (예: smartstore.naver.com/…)';
        hint.style.display = 'block';
        input.focus();
        input.style.borderColor = 'var(--danger)';
      }
    });
    input.addEventListener('input', function () { hint.style.display = 'none'; input.style.borderColor = ''; });
  });

  // 등록/수정/일괄 모달 열고 닫기
  document.querySelectorAll('[data-modal]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      var m = document.querySelector(el.dataset.modal); if (m) m.classList.add('on');
    });
  });
  document.querySelectorAll('.modal').forEach(function (m) {
    m.addEventListener('click', function (e) { if (e.target === m || e.target.closest('[data-close]')) m.classList.remove('on'); });
  });

  // 체크박스 → 일괄 등록 바
  var chks = document.querySelectorAll('.rowchk'), bar = document.getElementById('bulkBar');
  function refreshBulk() {
    var sel = document.querySelectorAll('.rowchk:checked');
    if (bar) { bar.style.display = sel.length ? 'flex' : 'none'; document.getElementById('bulkCount').textContent = sel.length; }
    var c = document.getElementById('bulkFillCount'); if (c) c.textContent = sel.length + '개';
    var form = document.getElementById('bulkFillForm');
    if (form) {
      form.querySelectorAll('input[name="ids"]').forEach(function (i) { i.remove(); });
      sel.forEach(function (cb) {
        var i = document.createElement('input'); i.type = 'hidden'; i.name = 'ids'; i.value = cb.value; form.appendChild(i);
      });
    }
  }
  chks.forEach(function (c) { c.addEventListener('change', refreshBulk); c.addEventListener('click', function (e) { e.stopPropagation(); }); });
  var all = document.getElementById('chkAll');
  if (all) all.addEventListener('change', function () { chks.forEach(function (c) { c.checked = all.checked; }); refreshBulk(); });

  // 등록/수정 후 돌아오면 해당 행만 강조(모달 자동 오픈 안 함)
  if (window.OPEN_ID) {
    var row = document.querySelector('tr[data-open="' + window.OPEN_ID + '"]');
    if (row) { row.classList.add('sel'); row.scrollIntoView({block: 'center', behavior: 'smooth'}); }
  }

  // ── 조회 대기중 행 자동 갱신: 순위/상품명이 도착하면 새로고침 없이 셀을 채운다 ──
  (function livePoll() {
    function pendingRows() {
      return Array.prototype.filter.call(document.querySelectorAll('tr[data-open]'), function (tr) {
        var rankTd = tr.querySelector('td[data-l="순위"]');
        var nameTd = tr.querySelector('td[data-l="상품명"]');
        var waitingRank = rankTd && rankTd.querySelector('.waiting');
        var waitingName = nameTd && nameTd.textContent.indexOf('자동 등록') !== -1;
        return waitingRank || waitingName;
      });
    }
    var tries = 0;
    function tick() {
      var rows = pendingRows();
      if (!rows.length || tries++ > 60) return;          // 최대 ~4분
      var ids = rows.map(function (tr) { return tr.dataset.open; }).join(',');
      fetch(window.RANKS_BASE + 'status?ids=' + ids, { credentials: 'include' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          (d.rows || []).forEach(function (c) {
            var tr = document.querySelector('tr[data-open="' + c.id + '"]');
            if (!tr) return;
            var rankTd = tr.querySelector('td[data-l="순위"]');
            var nameTd = tr.querySelector('td[data-l="상품명"]');
            if (rankTd && rankTd.querySelector('.waiting') && c.rankNow !== null && c.rankNow !== undefined) {
              var d0 = (c.rankStart || c.rankNow) - c.rankNow;
              rankTd.innerHTML = '<span class="rank num">' + (c.rankStart || c.rankNow) + ' → <b>' + c.rankNow + '</b>' +
                (d0 > 0 ? '<span class="up">▲' + d0 + '</span>' : d0 < 0 ? '<span class="dn">▼' + (-d0) + '</span>' : '') + '</span>';
            }
            if (nameTd && c.productName && nameTd.textContent.indexOf('자동 등록') !== -1) {
              nameTd.innerHTML = '<b title="' + c.productName.replace(/"/g, '&quot;') + '">' + c.productName + '</b>';
            }
          });
          setTimeout(tick, 4000);
        })
        .catch(function () { setTimeout(tick, 8000); });
    }
    if (pendingRows().length) setTimeout(tick, 2500);
  })();
})();
