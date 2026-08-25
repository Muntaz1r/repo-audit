class RepoAuditApp {
  constructor() {
    this.currentAudit = null;
    this.pollTimeout = null;
    this.activePollId = null;
    this.currentView = null;
    this.activeFilter = 'all';
    this.activePillar = 'code_eval';
    this.scopeFilter = 'active'; // 'active' or 'all_pillars'
    this.tooltipEl = null;
    this.init();
  }

  init() {
    this.tooltipEl = document.getElementById('global-tooltip');
    this.initGlobalEvents();

    const path = window.location.pathname;
    const match = path.match(/\/report\/([a-zA-Z0-9_]+)/);
    if (match) {
      this.loadAudit(match[1]);
    } else {
      this.showView('input');
    }

    const input = document.getElementById('repo-url-input');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          this.submitAudit();
        }
      });
    }
  }

  initGlobalEvents() {
    // Global Escape Key Listener for modal
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.closeMethodologyModal();
      }
    });

    // Global Tooltip listeners on pointer hover
    document.addEventListener('mouseover', (e) => {
      const target = e.target.closest('[data-tooltip]');
      if (target && this.tooltipEl) {
        const text = target.getAttribute('data-tooltip');
        if (text) {
          this.tooltipEl.innerText = text;
          this.tooltipEl.classList.add('visible');
          this.positionTooltip(e);
        }
      }
    });

    document.addEventListener('mousemove', (e) => {
      if (this.tooltipEl && this.tooltipEl.classList.contains('visible')) {
        this.positionTooltip(e);
      }
    });

    document.addEventListener('mouseout', (e) => {
      const target = e.target.closest('[data-tooltip]');
      if (target && this.tooltipEl) {
        this.tooltipEl.classList.remove('visible');
      }
    });

    // Global Tap-to-expand listener for truncated elements (Touch & Click fallback)
    document.addEventListener('click', (e) => {
      const expandable = e.target.closest('.tap-expandable');
      if (expandable) {
        // If clicking a link or interactive button inside it, don't interfere
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A' || e.target.closest('.finding-header')) {
          return;
        }
        expandable.classList.toggle('is-expanded');
      }
    });
  }

  positionTooltip(e) {
    if (!this.tooltipEl) return;
    const padding = 12;
    let x = e.clientX + padding;
    let y = e.clientY + padding;

    // Check viewport edges
    const rect = this.tooltipEl.getBoundingClientRect();
    if (x + rect.width > window.innerWidth - padding) {
      x = e.clientX - rect.width - padding;
    }
    if (y + rect.height > window.innerHeight - padding) {
      y = e.clientY - rect.height - padding;
    }

    this.tooltipEl.style.left = `${Math.max(padding, x)}px`;
    this.tooltipEl.style.top = `${Math.max(padding, y)}px`;
  }

  /* ==========================================================================
     METHODOLOGY MODAL CONTROLLERS
     ========================================================================== */
  openMethodologyModal() {
    const modal = document.getElementById('methodology-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden'; // Prevent background scrolling
    }
  }

  closeMethodologyModal(e) {
    if (e && e.target && e.target.closest('.modal-dialog')) {
      return;
    }
    const modal = document.getElementById('methodology-modal');
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = '';
    }
  }

  switchMethodologyTab(tabId) {
    const tabs = document.querySelectorAll('.modal-tab-btn');
    tabs.forEach(tab => {
      if (tab.dataset.tab === tabId) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    const panes = document.querySelectorAll('.modal-content-area .tab-pane');
    panes.forEach(pane => {
      if (pane.id === `tab-${tabId}`) {
        pane.style.display = 'block';
      } else {
        pane.style.display = 'none';
      }
    });
  }

  /* ==========================================================================
     VIEW NAVIGATION & INGESTION
     ========================================================================== */
  stopPolling() {
    if (this.pollTimeout) {
      clearTimeout(this.pollTimeout);
      this.pollTimeout = null;
    }
    this.activePollId = null;
  }

  showView(viewName, { resetScroll = true } = {}) {
    const isViewChange = this.currentView !== viewName;
    this.currentView = viewName;

    document.getElementById('view-input').style.display = viewName === 'input' ? 'block' : 'none';
    document.getElementById('view-loading').style.display = viewName === 'loading' ? 'block' : 'none';
    document.getElementById('view-report').style.display = viewName === 'report' ? 'block' : 'none';

    if (viewName === 'input') {
      window.history.pushState({}, '', '/');
      this.stopPolling();
    }
    if (isViewChange && resetScroll) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  setSampleRepo(url) {
    document.getElementById('repo-url-input').value = url;
    document.getElementById('input-error').style.display = 'none';
  }

  async submitAudit() {
    const input = document.getElementById('repo-url-input');
    const errorEl = document.getElementById('input-error');
    const btn = document.getElementById('btn-audit');
    const url = input.value.trim();

    errorEl.style.display = 'none';

    if (!url) {
      errorEl.innerText = 'Please provide a valid GitHub repository URL.';
      errorEl.style.display = 'block';
      return;
    }

    btn.disabled = true;
    btn.innerText = 'Submitting...';

    try {
      const response = await fetch('/api/audits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: url })
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to submit audit job.');
      }

      const audit = await response.json();
      this.startPolling(audit.id);
    } catch (err) {
      errorEl.innerText = err.message;
      errorEl.style.display = 'block';
      btn.disabled = false;
      btn.innerText = 'Audit Repository ↵';
    }
  }

  startPolling(auditId) {
    this.stopPolling();
    this.activePollId = auditId;

    this.showView('loading');
    const jobEl = document.getElementById('loading-job-id');
    jobEl.innerText = `pipeline-job #${auditId}`;
    jobEl.setAttribute('data-tooltip', `Audit Identifier: ${auditId}`);
    document.getElementById('loading-error').style.display = 'none';

    this.updateLoadingSteps('QUEUED');

    const poll = async () => {
      if (this.activePollId !== auditId) return;

      try {
        const response = await fetch(`/api/audits/${auditId}`);
        if (this.activePollId !== auditId) return;

        if (!response.ok) {
          this.pollTimeout = setTimeout(poll, 1500);
          return;
        }

        const data = await response.json();
        if (this.activePollId !== auditId) return;

        this.currentAudit = data;
        this.updateLoadingSteps(data.status, data.logs);

        if (data.status === 'COMPLETED') {
          this.stopPolling();
          window.history.pushState({}, '', `/report/${auditId}`);
          this.renderReport(data);
          return;
        } else if (data.status === 'FAILED') {
          this.stopPolling();
          const errEl = document.getElementById('loading-error');
          errEl.innerText = `Audit failed: ${data.error_message || 'Unknown analysis error'}`;
          errEl.style.display = 'block';
          return;
        }

        // Only schedule next poll tick after current request has completed
        this.pollTimeout = setTimeout(poll, 1500);
      } catch (e) {
        console.error('Polling error:', e);
        if (this.activePollId === auditId) {
          this.pollTimeout = setTimeout(poll, 1500);
        }
      }
    };

    this.pollTimeout = setTimeout(poll, 1500);
  }

  async loadAudit(auditId) {
    this.stopPolling();
    this.showView('loading');
    const jobEl = document.getElementById('loading-job-id');
    jobEl.innerText = `pipeline-job #${auditId}`;
    jobEl.setAttribute('data-tooltip', `Audit Identifier: ${auditId}`);

    try {
      const response = await fetch(`/api/audits/${auditId}`);
      if (!response.ok) throw new Error('Audit not found');
      const data = await response.json();
      this.currentAudit = data;

      if (data.status === 'COMPLETED') {
        this.renderReport(data);
      } else {
        this.startPolling(auditId);
      }
    } catch (err) {
      this.showView('input');
      const errorEl = document.getElementById('input-error');
      errorEl.innerText = 'Could not load audit report. Please try again.';
      errorEl.style.display = 'block';
    }
  }

  updateLoadingSteps(status, logs = []) {
    const s1 = document.getElementById('step-metadata');
    const s2 = document.getElementById('step-clone');
    const s3 = document.getElementById('step-analyze');
    const s4 = document.getElementById('step-verdict');

    [s1, s2, s3, s4].forEach(el => el.className = 'p-step');

    if (status === 'QUEUED') {
      s1.className = 'p-step active';
    } else if (status === 'CLONING') {
      s1.className = 'p-step done';
      s2.className = 'p-step active';
    } else if (status === 'ANALYZING') {
      s1.className = 'p-step done';
      s2.className = 'p-step done';
      s3.className = 'p-step active';
    } else if (status === 'COMPLETED') {
      [s1, s2, s3, s4].forEach(el => el.className = 'p-step done');
    }
  }

  /* ==========================================================================
     REPORT RENDERING & PILLARS
     ========================================================================== */
  renderReport(audit) {
    this.showView('report');

    document.getElementById('btn-audit').disabled = false;
    document.getElementById('btn-audit').innerText = 'Audit Repository ↵';

    const repoFullName = `${audit.owner}/${audit.repo_name}`;
    const repoTitleEl = document.getElementById('report-repo-name');
    repoTitleEl.innerText = repoFullName;
    repoTitleEl.setAttribute('data-tooltip', `Repository: ${repoFullName} (Tap to expand/copy)`);

    document.getElementById('report-branch').innerText = audit.default_branch || 'main';
    document.getElementById('report-stars').innerText = `⭐ ${Number(audit.stars_count || 0).toLocaleString()}`;
    document.getElementById('report-meta-sub').innerText = `Language: ${audit.primary_language || 'Various'} · Audited at ${new Date(audit.created_at).toLocaleTimeString()}`;

    // Verdict Hero
    const score = audit.overall_score || 0;
    const grade = audit.overall_grade || 'C';
    document.getElementById('report-score').innerText = score;
    document.getElementById('report-grade').innerText = `GRADE ${grade}`;
    
    const summaryEl = document.getElementById('report-verdict-summary');
    summaryEl.innerText = audit.verdict_summary || 'Review complete.';
    summaryEl.setAttribute('data-tooltip', 'Tap summary to expand or collapse');

    const badge = document.getElementById('report-verdict-badge');
    const ring = document.getElementById('gauge-ring-el');

    if (score >= 80) {
      badge.innerText = '✓ PRODUCTION READY';
      badge.style.color = 'var(--green)';
      badge.style.borderColor = 'var(--green)';
      badge.style.background = 'var(--green-glow)';
      ring.style.borderTopColor = 'var(--green)';
      ring.style.borderRightColor = 'var(--green)';
      ring.style.borderLeftColor = 'var(--green)';
      ring.style.boxShadow = '0 0 24px var(--green-glow)';
    } else if (score >= 65) {
      badge.innerText = '⚠ NEEDS REFACTORING';
      badge.style.color = 'var(--amber)';
      badge.style.borderColor = 'var(--amber)';
      badge.style.background = 'var(--amber-glow)';
      ring.style.borderTopColor = 'var(--amber)';
      ring.style.borderRightColor = 'var(--amber)';
      ring.style.borderLeftColor = 'var(--amber)';
      ring.style.boxShadow = '0 0 24px var(--amber-glow)';
    } else {
      badge.innerText = '✕ HIGH RISK';
      badge.style.color = 'var(--red)';
      badge.style.borderColor = 'var(--red)';
      badge.style.background = 'var(--red-glow)';
      ring.style.borderTopColor = 'var(--red)';
      ring.style.borderRightColor = 'var(--red)';
      ring.style.borderLeftColor = 'var(--red)';
      ring.style.boxShadow = '0 0 24px var(--red-glow)';
    }

    // Code Eval Metrics
    const codePillar = audit.pillars.find(p => p.pillar_key === 'code_eval');
    const metrics = codePillar ? codePillar.metrics_json : {};

    document.getElementById('metric-loc').innerHTML = `${Number(metrics.total_loc || 0).toLocaleString()} <span style="font-size:14px; font-weight:400; color:var(--text-muted)">LOC</span>`;
    document.getElementById('metric-files').innerText = `${metrics.total_code_files || 0} source files`;
    document.getElementById('metric-test-ratio').innerText = `${metrics.test_to_source_ratio || 0} : 1`;
    document.getElementById('metric-test-sub').innerText = `${metrics.test_files_count || 0} test files detected`;
    document.getElementById('metric-complexity').innerText = metrics.avg_cyclomatic_complexity || '0.0';
    document.getElementById('metric-maintainability').innerText = `${metrics.maintainability_index || 0} / 100`;

    // Render 5 Pillars
    this.renderPillarsNav(audit.pillars);

    // Render Findings
    this.renderFindings();
  }

  selectPillar(pillarKey) {
    this.activePillar = pillarKey;
    this.scopeFilter = 'active';
    this.activeFilter = 'all'; // reset severity filter so all findings for that pillar are visible
    this.renderPillarsNav(this.currentAudit.pillars);
    this.renderFindings();
  }

  renderPillarsNav(pillars) {
    const nav = document.getElementById('pillars-nav-list');
    nav.innerHTML = '';

    const pillarMeta = {
      semantic: { num: 'PILLAR 01', name: 'Semantic Analysis', badge: 'Gemini' },
      code_eval: { num: 'PILLAR 02 (MVP)', name: 'Code Evaluation', badge: 'Live AST' },
      security: { num: 'PILLAR 03', name: 'Security & Vulns', badge: 'Live Scanner' },
      docs: { num: 'PILLAR 04', name: 'Documentation', badge: 'Live AST' },
      prod_readiness: { num: 'PILLAR 05', name: 'Prod Readiness', badge: 'Live DevOps' },
    };

    const allFindings = this.currentAudit ? (this.currentAudit.findings || []) : [];

    pillars.forEach(p => {
      const meta = pillarMeta[p.pillar_key] || { num: 'PILLAR', name: p.pillar_key, badge: 'Preview' };
      const card = document.createElement('div');
      const pFindingsCount = allFindings.filter(f => f.pillar_key === p.pillar_key).length;
      card.className = `p-card ${this.activePillar === p.pillar_key ? 'active' : ''} tap-expandable`;
      card.setAttribute('data-tooltip', `Pillar: ${meta.name} (Score: ${p.score}/100)`);
      card.onclick = () => this.selectPillar(p.pillar_key);

      const scoreClass = p.score >= 85 ? 'high' : (p.score >= 65 ? 'med' : '');

      card.innerHTML = `
        <div>
          <div class="p-card-num mono">${meta.num}</div>
          <div class="p-card-name">${meta.name}</div>
        </div>
        <div>
          <div class="p-card-score mono ${scoreClass}">${p.score} <span class="p-badge-preview">${meta.badge}</span></div>
          <div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:4px;">${pFindingsCount} finding${pFindingsCount === 1 ? '' : 's'}</div>
        </div>
      `;
      nav.appendChild(card);
    });
  }

  setFilter(severity) {
    this.activeFilter = severity;
    const filterPills = document.querySelectorAll('#severity-filters .f-pill');
    filterPills.forEach(p => p.classList.remove('active'));

    const activePill = Array.from(filterPills).find(p => p.dataset.severity === severity);
    if (activePill) activePill.classList.add('active');

    this.renderFindings();
  }

  showAllPillarsFindings() {
    this.scopeFilter = 'all_pillars';
    this.renderFindings();
  }

  renderFindings() {
    if (!this.currentAudit) return;

    // Update active filter pill classes based on data-severity
    const filterPills = document.querySelectorAll('#severity-filters .f-pill');
    filterPills.forEach(p => {
      if (p.dataset.severity === this.activeFilter) {
        p.classList.add('active');
      } else {
        p.classList.remove('active');
      }
    });

    // Render Semantic Architecture view if Pillar 01 is active
    const semanticView = document.getElementById('semantic-architecture-view');
    if (this.activePillar === 'semantic') {
      const semanticPillar = this.currentAudit.pillars.find(p => p.pillar_key === 'semantic');
      const sm = semanticPillar ? semanticPillar.metrics_json : {};
      
      semanticView.style.display = 'block';
      semanticView.innerHTML = `
        <div class="semantic-head">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="arch-type-badge">${this.escapeHtml(sm.architecture_type || 'Modular Architecture')}</span>
            <span class="semantic-engine-badge">⚡ ${this.escapeHtml(sm.engine || 'Semantic Engine')}</span>
          </div>
        </div>

        <div style="margin-bottom:18px;">
          <h4 style="font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">Purpose &amp; Architecture Summary</h4>
          <p class="tap-expandable" data-tooltip="Tap to expand full purpose summary" style="font-size:13px; color:var(--text-primary); line-height:1.7;">${this.escapeHtml(sm.purpose_summary || 'No purpose summary generated.')}</p>
        </div>

        ${sm.data_flow_summary ? `
        <div style="margin-bottom:18px;">
          <h4 style="font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">Data Flow &amp; Execution Lifecycle</h4>
          <p class="tap-expandable" data-tooltip="Tap to expand full data flow details" style="font-size:13px; color:var(--text-muted); line-height:1.6;">${this.escapeHtml(sm.data_flow_summary)}</p>
        </div>` : ''}

        ${sm.design_patterns && sm.design_patterns.length > 0 ? `
        <div style="margin-bottom:18px;">
          <h4 style="font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">Detected Design Patterns</h4>
          <div class="patterns-pills">
            ${sm.design_patterns.map(dp => `<span class="pattern-pill mono tap-expandable" data-tooltip="Design Pattern: ${this.escapeHtml(dp)}">${this.escapeHtml(dp)}</span>`).join('')}
          </div>
        </div>` : ''}

        ${sm.key_modules && sm.key_modules.length > 0 ? `
        <div style="margin-top:20px;">
          <h4 style="font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Discovered Key Modules &amp; Topology</h4>
          <div class="modules-grid">
            ${sm.key_modules.map(mod => `
              <div class="module-card">
                <div class="module-name tap-expandable" data-tooltip="Module: ${this.escapeHtml(mod.name)}">${this.escapeHtml(mod.name)}</div>
                <div class="module-path mono tap-expandable" data-tooltip="${this.escapeHtml(mod.path)}">${this.escapeHtml(mod.path)}</div>
                <div class="module-purpose tap-expandable" data-tooltip="Tap to expand module description">${this.escapeHtml(mod.purpose)}</div>
              </div>
            `).join('')}
          </div>
        </div>` : ''}
      `;
    } else {
      semanticView.style.display = 'none';
    }

    // Render Security view if Pillar 03 is active
    const securityView = document.getElementById('security-architecture-view');
    if (this.activePillar === 'security') {
      const securityPillar = this.currentAudit.pillars.find(p => p.pillar_key === 'security');
      const sec = securityPillar ? securityPillar.metrics_json : {};
      const secClean = (sec.secret_findings_count || 0) === 0;
      const vulnClean = (sec.vulnerability_findings_count || 0) === 0;

      securityView.style.display = 'block';
      securityView.innerHTML = `
        <div class="semantic-head">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="sec-stat-badge ${secClean ? 'sec-badge-clean' : 'sec-badge-danger'}">
              ${secClean ? '✓ Secrets Clean' : `⚠ ${sec.secret_findings_count} Exposed Secret(s)`}
            </span>
            <span class="sec-stat-badge ${vulnClean ? 'sec-badge-clean' : 'sec-badge-danger'}">
              ${vulnClean ? '✓ Dependencies Clean' : `⚠ ${sec.vulnerability_findings_count} CVE Vulnerabilit(ies)`}
            </span>
          </div>
          <span class="mono" style="font-size:12px; color:var(--text-muted);">
            Scanned ${sec.total_files_scanned || 0} source files &amp; ${sec.total_dependencies_scanned || 0} dependencies
          </span>
        </div>

        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin-top:14px;">
          <div class="module-card">
            <div class="module-name" style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">Secret Scanner</div>
            <div class="mono" style="font-size:15px; font-weight:700; color:${secClean ? 'var(--green)' : 'var(--red)'}; margin:6px 0;">
              ${sec.secret_scanner_status || 'CLEAN'}
            </div>
            <div style="font-size:12px; color:var(--text-muted);">Scans for AWS, GitHub, JWT, Private Keys, Slack tokens.</div>
          </div>
          <div class="module-card">
            <div class="module-name" style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">Dependency Auditing</div>
            <div class="mono" style="font-size:15px; font-weight:700; color:${vulnClean ? 'var(--green)' : 'var(--red)'}; margin:6px 0;">
              ${sec.dependency_scanner_status || 'CLEAN'}
            </div>
            <div style="font-size:12px; color:var(--text-muted);">Audits package.json, requirements.txt, go.mod for CVEs.</div>
          </div>
        </div>
      `;
    } else {
      if (securityView) securityView.style.display = 'none';
    }

    // Render Documentation view if Pillar 04 is active
    const docsView = document.getElementById('docs-architecture-view');
    if (this.activePillar === 'docs') {
      const docsPillar = this.currentAudit.pillars.find(p => p.pillar_key === 'docs');
      const doc = docsPillar ? docsPillar.metrics_json : {};
      const sections = doc.readme_sections || {};
      const cov = doc.docstring_coverage_pct || 0;

      docsView.style.display = 'block';
      docsView.innerHTML = `
        <div class="semantic-head">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="sec-stat-badge ${doc.has_readme ? 'sec-badge-clean' : 'sec-badge-danger'}">
              ${doc.has_readme ? `✓ README (${doc.readme_word_count || 0} words)` : '✕ Missing README'}
            </span>
            <span class="sec-stat-badge ${doc.has_license ? 'sec-badge-clean' : 'sec-badge-warn'}">
              ${doc.has_license ? `✓ License Found (${doc.license_file || 'Declared'})` : '⚠ Missing License'}
            </span>
            <span class="sec-stat-badge ${cov >= 50 ? 'sec-badge-clean' : (cov >= 25 ? 'sec-badge-warn' : 'sec-badge-danger')}">
              ${cov}% Docstring Coverage
            </span>
          </div>
          <span class="mono" style="font-size:12px; color:var(--text-muted);">
            ${doc.documented_symbols || 0} / ${doc.total_symbols_scanned || 0} public functions &amp; classes documented
          </span>
        </div>

        <div style="margin-top:16px;">
          <h4 style="font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">README Structure &amp; Onboarding Sections</h4>
          <div class="checklist-grid">
            <div class="check-item ${sections.overview ? 'passed' : 'missing'}">
              <span class="check-icon ${sections.overview ? 'passed' : 'missing'}">${sections.overview ? '✓' : '✕'}</span>
              <span>Overview &amp; About</span>
            </div>
            <div class="check-item ${sections.installation ? 'passed' : 'missing'}">
              <span class="check-icon ${sections.installation ? 'passed' : 'missing'}">${sections.installation ? '✓' : '✕'}</span>
              <span>Installation / Setup</span>
            </div>
            <div class="check-item ${sections.usage ? 'passed' : 'missing'}">
              <span class="check-icon ${sections.usage ? 'passed' : 'missing'}">${sections.usage ? '✓' : '✕'}</span>
              <span>Usage / Quickstart</span>
            </div>
            <div class="check-item ${sections.configuration ? 'passed' : 'missing'}">
              <span class="check-icon ${sections.configuration ? 'passed' : 'missing'}">${sections.configuration ? '✓' : '✕'}</span>
              <span>Configuration / API</span>
            </div>
            <div class="check-item ${sections.contributing ? 'passed' : 'missing'}">
              <span class="check-icon ${sections.contributing ? 'passed' : 'missing'}">${sections.contributing ? '✓' : '✕'}</span>
              <span>Contributing Guide</span>
            </div>
            <div class="check-item ${sections.license ? 'passed' : 'missing'}">
              <span class="check-icon ${sections.license ? 'passed' : 'missing'}">${sections.license ? '✓' : '✕'}</span>
              <span>License Section</span>
            </div>
          </div>
        </div>
      `;
    } else {
      if (docsView) docsView.style.display = 'none';
    }

    // Render Production Readiness view if Pillar 05 is active
    const prodView = document.getElementById('prod-architecture-view');
    if (this.activePillar === 'prod_readiness') {
      const prodPillar = this.currentAudit.pillars.find(p => p.pillar_key === 'prod_readiness');
      const prod = prodPillar ? prodPillar.metrics_json : {};
      const ciFiles = prod.ci_files || [];
      const contFiles = prod.container_files || [];

      prodView.style.display = 'block';
      prodView.innerHTML = `
        <div class="semantic-head">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span class="sec-stat-badge ${prod.has_ci_cd ? 'sec-badge-clean' : 'sec-badge-warn'}">
              ${prod.has_ci_cd ? `✓ CI/CD Automation (${ciFiles.length} workflow${ciFiles.length === 1 ? '' : 's'})` : '⚠ Missing CI/CD'}
            </span>
            <span class="sec-stat-badge ${prod.has_containerization ? 'sec-badge-clean' : 'sec-badge-warn'}">
              ${prod.has_containerization ? `✓ Containerized (${contFiles.join(', ')})` : 'ℹ No Docker Specs'}
            </span>
            <span class="sec-stat-badge ${prod.has_gitignore ? 'sec-badge-clean' : 'sec-badge-danger'}">
              ${prod.has_gitignore ? '✓ .gitignore Present' : '✕ Missing .gitignore'}
            </span>
            <span class="sec-stat-badge ${prod.has_deterministic_lockfile ? 'sec-badge-clean' : 'sec-badge-warn'}">
              ${prod.has_deterministic_lockfile ? '✓ Lockfile Present' : '⚠ Missing Lockfile'}
            </span>
          </div>
          <span class="mono" style="font-size:12px; color:var(--text-muted);">
            DevOps &amp; Infrastructure Assessment
          </span>
        </div>

        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin-top:14px;">
          <div class="module-card">
            <div class="module-name" style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">CI/CD Workflows</div>
            <div class="mono tap-expandable" data-tooltip="CI configuration files" style="font-size:14px; font-weight:700; color:${prod.has_ci_cd ? 'var(--green)' : 'var(--amber)'}; margin:6px 0;">
              ${ciFiles.length > 0 ? ciFiles.slice(0, 2).join('<br>') : 'No CI configured'}
            </div>
            <div style="font-size:12px; color:var(--text-muted);">Automates tests and builds on PR/push.</div>
          </div>
          <div class="module-card">
            <div class="module-name" style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">Container Specs</div>
            <div class="mono tap-expandable" data-tooltip="Container configuration" style="font-size:14px; font-weight:700; color:${prod.has_containerization ? 'var(--green)' : 'var(--text-muted)'}; margin:6px 0;">
              ${contFiles.length > 0 ? contFiles.join(', ') : 'None'}
            </div>
            <div style="font-size:12px; color:var(--text-muted);">Standardizes runtime and host deployment.</div>
          </div>
          <div class="module-card">
            <div class="module-name" style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">Structured Logging</div>
            <div class="mono" style="font-size:14px; font-weight:700; color:${prod.has_structured_logging ? 'var(--green)' : 'var(--text-muted)'}; margin:6px 0;">
              ${prod.has_structured_logging ? 'Structured Logging Detected' : 'Raw Console Logging'}
            </div>
            <div style="font-size:12px; color:var(--text-muted);">Production observability and error aggregation.</div>
          </div>
        </div>
      `;
    } else {
      if (prodView) prodView.style.display = 'none';
    }

    const pillarNames = {
      semantic: 'Semantic Analysis',
      code_eval: 'Code Evaluation',
      security: 'Security & Vulnerability',
      docs: 'Documentation Quality',
      prod_readiness: 'Production Readiness',
    };

    const allFindings = this.currentAudit.findings || [];
    let findings = allFindings;

    if (this.scopeFilter === 'active') {
      findings = allFindings.filter(f => f.pillar_key === this.activePillar);
    }

    const activePillarName = pillarNames[this.activePillar] || this.activePillar;
    const headerEl = document.getElementById('findings-section-header');
    if (headerEl) {
      if (this.scopeFilter === 'active') {
        headerEl.innerHTML = `Findings for <strong>${activePillarName}</strong> <span style="font-weight:400; color:var(--text-muted); font-size:13px;">(${findings.length} findings)</span>`;
      } else {
        headerEl.innerHTML = `All Findings across All Pillars <span style="font-weight:400; color:var(--text-muted); font-size:13px;">(${allFindings.length} total)</span>`;
      }
    }

    const searchVal = (document.getElementById('search-findings-input').value || '').toLowerCase();

    // Update counts based on current scoped findings
    document.getElementById('count-all').innerText = findings.length;
    document.getElementById('count-critical').innerText = findings.filter(f => f.severity === 'critical').length;
    document.getElementById('count-warning').innerText = findings.filter(f => f.severity === 'warning').length;
    document.getElementById('count-info').innerText = findings.filter(f => f.severity === 'info').length;

    // Filter by severity
    let filtered = findings;
    if (this.activeFilter !== 'all') {
      filtered = filtered.filter(f => f.severity === this.activeFilter);
    }
    if (searchVal) {
      filtered = filtered.filter(f => 
        (f.title && f.title.toLowerCase().includes(searchVal)) ||
        (f.file_path && f.file_path.toLowerCase().includes(searchVal)) ||
        (f.description && f.description.toLowerCase().includes(searchVal))
      );
    }

    const listEl = document.getElementById('findings-list');

    if (filtered.length === 0) {
      if (findings.length === 0 && allFindings.length > 0 && this.scopeFilter === 'active') {
        listEl.innerHTML = `
          <div style="text-align:center; padding:32px 18px; color:var(--text-muted); background:var(--bg-canvas); border-radius:var(--radius-md); border:1px solid var(--border);">
            <div style="font-size:16px; font-weight:600; margin-bottom:6px; color:var(--green);">✓ No findings in ${activePillarName}</div>
            <p style="font-size:12px; margin-bottom:14px;">This pillar passed without any detected risks.</p>
            <button class="btn-outline" onclick="app.showAllPillarsFindings()" style="font-size:12px;">View all ${allFindings.length} findings in other pillars →</button>
          </div>
        `;
      } else {
        listEl.innerHTML = `
          <div style="text-align:center; padding:32px; color:var(--text-muted);">
            <div class="mono" style="font-size:13px;">No findings matched the current filter.</div>
          </div>
        `;
      }
      return;
    }

    listEl.innerHTML = filtered.map((f, idx) => `
      <div class="finding-item">
        <div class="finding-header" onclick="app.toggleFinding(this)">
          <div class="finding-meta-left">
            <span class="sev-tag sev-${f.severity}">${f.severity}</span>
            <span class="finding-title tap-expandable" data-tooltip="Tap to expand finding title">${this.escapeHtml(f.title)}</span>
            ${f.file_path ? `<span class="finding-file mono tap-expandable" data-tooltip="${this.escapeHtml(f.file_path)}">${this.escapeHtml(f.file_path)}${f.line_start ? `:L${f.line_start}` : ''}</span>` : ''}
          </div>
          <div class="mono" style="color:var(--text-muted); font-size:12px;">Details ▾</div>
        </div>
        <div class="finding-body ${idx === 0 ? 'open' : ''}">
          <div class="finding-grid">
            <div class="f-col">
              <h4>What was found</h4>
              <p class="tap-expandable" data-tooltip="Tap to expand summary">${this.escapeHtml(f.description)}</p>
              ${f.impact ? `<h4 style="margin-top:12px;">Reviewer Impact</h4><p class="tap-expandable" data-tooltip="Tap to expand impact details">${this.escapeHtml(f.impact)}</p>` : ''}
            </div>
            <div class="f-col">
              ${f.recommendation ? `<h4>Recommended Fix</h4><p class="tap-expandable" data-tooltip="Tap to expand recommendation">${this.escapeHtml(f.recommendation)}</p>` : ''}
              ${f.code_snippet ? `<div class="code-snippet mono tap-expandable" data-tooltip="Tap to toggle code wrap">${this.escapeHtml(f.code_snippet)}</div>` : ''}
            </div>
          </div>
        </div>
      </div>
    `).join('');
  }

  toggleFinding(headerEl) {
    const body = headerEl.nextElementSibling;
    body.classList.toggle('open');
  }

  exportReport(format) {
    if (!this.currentAudit || !this.currentAudit.id) {
      alert('Please run an audit before exporting.');
      return;
    }
    const url = `/api/audits/${this.currentAudit.id}/export?format=${encodeURIComponent(format)}`;
    window.open(url, '_blank');
  }

  copyShareLink() {
    navigator.clipboard.writeText(window.location.href);
    alert('Report permalink copied to clipboard!');
  }

  escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}

window.app = new RepoAuditApp();
