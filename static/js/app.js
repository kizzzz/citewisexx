/* CiteWise V3 — 前端逻辑 (合并原型交互 + 后端 API) */

// ============ API Base URL (环境感知) ============
// 默认同源（''）：适用于本地开发与自托管部署（前端 + FastAPI 同一域名，例如 xx27.xyz）。
// 纯静态托管（Vercel / EdgeOne / Pages）没有后端，回退到独立后端地址。
// 需要手动指定后端时，在 index.html 里 app.js 之前设置 window.CITEWISE_API_BASE 即可覆盖。
const API_BASE = (typeof window.CITEWISE_API_BASE === 'string')
    ? window.CITEWISE_API_BASE
    : (/(\.vercel\.app|\.edgeone\.cool|\.pages\.dev|\.github\.io)$/.test(window.location.hostname)
        ? 'https://citewise-w9op.onrender.com'  // 静态托管：调用远端后端
        : '');  // 同源部署

// ============ State ============
let projects = [];
let currentProjectId = null;
let extractionFields = ['研究方法', '核心算法', '数据集', '主要结论'];
let currentDraftSection = null;
let chatBusy = false;
let currentDraftId = null;
let currentDraftName = '';
let currentUser = null; // { id, username, token }
let authMode = 'login'; // 'login' or 'register'
let currentSessionId = null; // 对话会话 ID（多轮对话）
let researchMaterials = []; // 写作素材收集（按项目存储）
let currentPapers = []; // 当前项目的文献列表

let agents = [
    { id: 'research', name: 'Research', icon: 'search', status: 'READY', color: 'blue',
      prompt: '你是一个专业的学术研究员。你的职责是检索、分析和总结学术文献。请使用严谨的学术语言，准确引用来源。',
      description: '负责文献检索、知识库 RAG 检索和联网搜索' },
    { id: 'writing', name: 'Writing', icon: 'pen-tool', status: 'READY', color: 'purple',
      prompt: '你是一个学术论文写作专家。你的职责是撰写和润色学术论文的各个章节。请遵循学术写作规范，确保逻辑清晰、表达准确。',
      description: '负责学术论文写作、章节生成和内容润色' },
    { id: 'analyst', name: 'Analyst', icon: 'hammer', status: 'READY', color: 'slate',
      prompt: '你是一个数据分析专家。你的职责是进行方法论对比、统计分析，并生成可视化图表。请使用准确的数据和清晰的逻辑进行分析。',
      description: '负责方法论对比、统计分析和数据可视化' }
];

let skills = [
    { id: 1, title: "Abstract Polisher", desc: "摘要润色能力。", icon: "pen-tool", tag: "已安装", agent: "writing" },
    { id: 2, title: "Citation Checker", desc: "引用格式与准确性验证。", icon: "check-circle", tag: "已安装", agent: "research" },
    { id: 3, title: "Method Comparator", desc: "方法论对比分析。", icon: "git-compare", tag: "已安装", agent: "analyst" },
    { id: 4, title: "Term Normalizer", desc: "术语一致性检查。", icon: "type", tag: "已安装", agent: "writing" }
];

// ============ Avatar Templates ============
const AI_AVATAR = `<div class="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-600 via-purple-500 to-blue-500 flex items-center justify-center shrink-0 shadow-md shadow-indigo-500/25 ring-2 ring-white/60"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 1.5L13.45 8.6Q13.55 9.15 14.05 9.3L21 12L14.05 14.7Q13.55 14.85 13.45 15.4L12 22.5L10.55 15.4Q10.45 14.85 9.95 14.7L3 12L9.95 9.3Q10.45 9.15 10.55 8.6Z" fill="white" fill-opacity="0.95"/><circle cx="12" cy="12" r="1.2" fill="white"/></svg></div>`;
const USER_AVATAR = `<div class="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-500 flex items-center justify-center shrink-0 shadow-md shadow-indigo-500/25 ring-2 ring-white/60"><svg viewBox="0 0 24 24" width="18" height="18" fill="none"><circle cx="12" cy="8.5" r="3.5" fill="white" fill-opacity="0.95"/><path d="M4.5 21C4.5 17.5 7.5 15 12 15C16.5 15 19.5 17.5 19.5 21" stroke="white" stroke-opacity="0.95" stroke-width="2" stroke-linecap="round"/></svg></div>`;

let tools = [
    { id: 1, title: "Statistical Plotter", desc: "自动根据文献数据绘制图表。", icon: "bar-chart-3", type: "脚本", trigger: "绘图, 画图, plot", agent: "analyst" },
    { id: 2, title: "Citation Formatter", desc: "处理引用格式。", icon: "book-open", type: "脚本", trigger: "格式, 引用, cite", agent: "research" }
];

let apiKeys = [
    { id: '1', name: 'Gemini 2.0 Flash', value: 'sk-xxxxxxxx', active: true }
];

// ============ Init ============
document.addEventListener('DOMContentLoaded', async () => {
    // Event delegation for data-action elements (XSS-safe replacement for inline onclick)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const id = btn.dataset.id;
        if (action === 'openPaper') {
            e.stopPropagation();
            openPaperDetail(id, btn.dataset.title, btn.dataset.authors);
        } else if (action === 'editTitle') {
            e.stopPropagation();
            startEditTitle(id, btn);
        } else if (action === 'deletePaper') {
            e.stopPropagation();
            deletePaper(id);
        } else if (action === 'openDraft') {
            openDraftEditor(id, btn.dataset.name);
        }
    });

    lucide.createIcons();
    renderAgentStatus();
    renderApiKeyList();

    // Restore user session BEFORE loading projects (needs token)
    const savedUser = localStorage.getItem('citewise_user');
    if (savedUser) {
        try {
            currentUser = JSON.parse(savedUser);
            updateAuthUI();
        } catch { currentUser = null; }
    }

    await loadProjects();
    renderSkillLibrary();
    renderToolLibrary();
    renderAgentCards();
    renderFields();

    // Restore last session ID
    const savedSession = localStorage.getItem('citewise_session');
    if (savedSession) {
        try { currentSessionId = JSON.parse(savedSession); } catch { currentSessionId = null; }
    }

    // Restore agent/skill/tool config from localStorage
    loadAgentConfig();
    const savedKeys = localStorage.getItem('citewise_api_keys');
    if (savedKeys) {
        try { apiKeys = JSON.parse(savedKeys); } catch { apiKeys = []; }
    }
    // Migrate old single-key format
    if (apiKeys.length === 0) {
        const oldKey = localStorage.getItem('citewise_api_key');
        if (oldKey) {
            apiKeys = [{ provider: 'zhipu', apiKey: oldKey, baseUrl: 'https://open.bigmodel.cn/api/paas/v4/', active: true }];
            saveApiKeysToStorage(apiKeys);
        }
    }
    renderApiKeyList();
    initModelSelector();

    // Enter key for chat input
    document.getElementById('chatInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSendChat();
    });
    document.getElementById('subInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendSubChat();
        }
    });

    // Close dropdowns on click outside
    window.addEventListener('click', () => {
        document.querySelectorAll('.dropdown-menu').forEach(d => d.classList.remove('show'));
        // Close model dropdown
        const mdl = document.getElementById('modelDropdownList');
        const mdb = document.getElementById('modelDropdownBtn');
        if (mdl) mdl.classList.remove('show');
        if (mdb) mdb.classList.remove('open');
    });
});

// ============ API Client ============
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    if (currentUser && currentUser.token) {
        opts.headers['Authorization'] = `Bearer ${currentUser.token}`;
    }
    const resp = await fetch(`${API_BASE}/api${path}`, opts);
    if (resp.status === 401) {
        // Token expired or invalid — force re-login
        currentUser = null;
        localStorage.removeItem('citewise_user');
        updateAuthUI();
        throw new Error('登录已过期，请重新登录');
    }
    if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err);
    }
    return resp;
}

// ============ Projects ============
async function loadProjects() {
    try {
        projects = await (await api('GET', '/projects')).json();
        if (projects.length === 0) {
            // Auto-create a default project so chat works immediately
            const resp = await (await api('POST', '/projects', { name: '默认研究项目', topic: '学术研究' })).json();
            projects = await (await api('GET', '/projects')).json();
        }
        renderProjectList();
        if (projects.length > 0 && !currentProjectId) {
            await selectProject(projects[0].id);
        }
    } catch (e) {
        console.error('Load projects failed:', e);
    }
}

async function selectProject(id) {
    currentProjectId = id;
    const proj = projects.find(p => p.id === id);
    document.getElementById('currentProjectName').textContent = proj ? proj.name : '未知项目';
    closeAllDropdowns();
    renderProjectList();
    loadMaterialsFromStorage();
    // Reset notes filter on project switch
    const filter = document.getElementById('noteTypeFilter');
    if (filter) filter.value = '';
    await loadProjectData();
}

async function loadProjectData() {
    if (!currentProjectId) return;
    try {
        const state = await (await api('GET', `/projects/${currentProjectId}/state`)).json();
        currentPapers = state.papers || [];
        renderPapers(currentPapers);
        renderDrafts(state.sections_with_id || []);
        // Restore session history if we have a saved session
        if (currentSessionId) {
            await loadSessionHistory();
        }
    } catch (e) {
        console.error('Load project data failed:', e);
    }
}

function renderProjectList() {
    const c = document.getElementById('projectListContainer');
    if (!c) return;
    c.innerHTML = projects.map(p =>
        `<div class="group flex items-center justify-between p-3 hover:bg-blue-50 cursor-pointer rounded-lg font-bold ${p.id === currentProjectId ? 'bg-blue-50 text-blue-700' : 'text-slate-700'}">
            <span onclick="selectProject('${escapeAttr(p.id)}')" class="flex-1 truncate">${escapeHtml(p.name)}</span>
            <button onclick="event.stopPropagation();confirmDeleteProject('${escapeAttr(p.id)}','${escapeJs(p.name)}')" class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-opacity ml-2" title="删除项目">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
            </button>
        </div>`
    ).join('');
    lucide.createIcons();
}

async function confirmDeleteProject(id, name) {
    if (!confirm(`确定删除项目「${name}」？该操作不可恢复。`)) return;
    try {
        await api('DELETE', `/projects/${id}`);
        showToast('项目已删除', 'success');
        if (currentProjectId === id) currentProjectId = null;
        await loadProjects();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

async function confirmCreateProject() {
    const name = document.getElementById('newProjectTitle').value.trim();
    const topic = document.getElementById('newProjectTopic') ? document.getElementById('newProjectTopic').value.trim() : '';
    if (!name) return;
    try {
        const resp = await (await api('POST', '/projects', { name, topic })).json();
        toggleModal('newProjectModal');
        showToast('项目创建成功', 'success');
        await loadProjects();
        await selectProject(resp.id);
    } catch (e) {
        showToast('创建失败: ' + e.message, 'error');
    }
}

// ============ Papers ============
function renderPapers(papers) {
    const c = document.getElementById('paperListContainer');
    if (!c) return;
    if (!papers || papers.length === 0) {
        c.innerHTML = '<div class="col-span-3 text-center text-slate-400 py-12">暂无文献，请上传 PDF</div>';
        return;
    }
    c.innerHTML = papers.map(p =>
        `<div class="interactive-card group relative bg-white p-6 rounded-3xl border border-slate-100 shadow-sm animate__animated animate__fadeIn cursor-pointer" data-action="openPaper" data-id="${escapeAttr(p.id)}" data-title="${escapeAttr(p.title)}" data-authors="${escapeAttr(p.authors || '')}">
            <div class="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-10">
                <button data-action="editTitle" data-id="${escapeAttr(p.id)}" class="w-7 h-7 rounded-full bg-slate-100 hover:bg-blue-100 text-slate-400 hover:text-blue-600 flex items-center justify-center transition-colors" title="重命名">
                    <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                </button>
                <button data-action="deletePaper" data-id="${escapeAttr(p.id)}" class="w-7 h-7 rounded-full bg-slate-100 hover:bg-red-100 text-slate-400 hover:text-red-500 flex items-center justify-center transition-colors" title="删除">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
            </div>
            <div class="w-10 h-10 bg-blue-50 text-blue-600 rounded-xl flex items-center justify-center mb-4">
                <i data-lucide="file-text" class="w-5 h-5"></i>
            </div>
            <h4 class="paper-title font-bold text-slate-800 text-sm mb-1" data-title="${escapeHtml(p.title || '未命名')}">${escapeHtml(p.title || '未命名')}</h4>
            <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider">${p.year || '?'} · ${escapeHtml((p.authors || '').substring(0, 20))}</p>
        </div>`
    ).join('');
    lucide.createIcons();
}

function startEditTitle(paperId, btnEl) {
    const card = btnEl.closest('.interactive-card');
    const h4 = card.querySelector('.paper-title');
    const currentTitle = h4.dataset.title || h4.textContent.trim();

    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentTitle;
    input.className = 'w-full font-bold text-slate-800 text-sm border border-blue-300 rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-blue-200';

    h4.replaceWith(input);
    input.focus();
    input.select();

    const save = async () => {
        const newTitle = input.value.trim();
        input.removeEventListener('blur', save);
        input.removeEventListener('keydown', onKey);

        if (!newTitle || newTitle === currentTitle) {
            restoreTitle(input, currentTitle);
            return;
        }
        try {
            await api('PATCH', `/papers/${paperId}/title`, { title: newTitle });
            updatePaperTitle(paperId, newTitle);
            restoreTitle(input, newTitle);
            showToast('标题已更新', 'success');
        } catch (e) {
            restoreTitle(input, currentTitle);
            showToast('更新失败: ' + e.message, 'error');
        }
    };

    const onKey = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') { input.removeEventListener('blur', save); input.removeEventListener('keydown', onKey); restoreTitle(input, currentTitle); }
    };

    input.addEventListener('blur', save);
    input.addEventListener('keydown', onKey);
}

function restoreTitle(input, title) {
    const h4 = document.createElement('h4');
    h4.className = 'paper-title font-bold text-slate-800 text-sm mb-1';
    h4.dataset.title = title;
    h4.textContent = title;
    input.replaceWith(h4);
}

function updatePaperTitle(paperId, newTitle) {
    const p = currentPapers.find(x => x.id === paperId);
    if (p) p.title = newTitle;
}

async function deletePaper(paperId) {
    const p = currentPapers.find(x => x.id === paperId);
    const name = p?.title || '该文献';
    if (!confirm(`确定删除「${name}」？此操作不可恢复。`)) return;

    try {
        await api('DELETE', `/papers/${paperId}?project_id=${currentProjectId}`);
        currentPapers = currentPapers.filter(x => x.id !== paperId);
        renderPapers(currentPapers);
        showToast('已删除', 'success');
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

async function handleUploadPapers() {
    const files = document.getElementById('paperUpload').files;
    if (!files.length || !currentProjectId) {
        showToast('请先选择项目', 'error');
        return;
    }

    if (files.length > 1) {
        showToast(`已选择 ${files.length} 个文件，开始上传...`);
    }

    const prog = document.getElementById('uploadProgress');
    prog.classList.remove('hidden');
    prog.classList.add('animate__animated', 'animate__fadeIn');

    const formData = new FormData();
    for (const f of files) formData.append('files', f);
    formData.append('project_id', currentProjectId);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/api/papers/upload`);
    if (currentUser && currentUser.token) {
        xhr.setRequestHeader('Authorization', `Bearer ${currentUser.token}`);
    }

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const pct = Math.round(e.loaded / e.total * 100);
            document.getElementById('progressBar').style.width = pct + '%';
            document.getElementById('progressText').textContent = pct + '%';
        }
    };

    xhr.onload = () => {
        prog.classList.add('hidden');
        if (xhr.status === 200) {
            try {
                const result = JSON.parse(xhr.responseText);
                showToast(result.message, 'success');
                loadProjectData();
            } catch (e) {
                showToast('上传完成，但解析响应失败', 'error');
            }
        } else {
            showToast('上传失败', 'error');
        }
    };

    xhr.onerror = () => {
        prog.classList.add('hidden');
        showToast('网络错误', 'error');
    };

    xhr.send(formData);
}

function handlePaperSelect(e) {
    if (e.target.files[0]) showToast('文献已选择', 'success');
}

function handleDragOver(e) {
    e.preventDefault();
}

function handleDragLeave(e) {
    e.preventDefault();
}

function handleDrop(e) {
    e.preventDefault();
    if (e.dataTransfer.files[0]) showToast('解析成功', 'success');
}

async function openPaperDetail(id, title, authors) {
    safeClassAction('paperListView', 'add', 'hidden');
    safeClassAction('paperDetailView', 'remove', 'hidden');
    document.getElementById('detailPaperDisplayTitle').textContent = title;

    const abstractEl = document.getElementById('abstractContent');
    const detailEl = document.getElementById('paperDetailContent');
    const metaEl = document.getElementById('detailPaperMeta');

    if (abstractEl) abstractEl.textContent = '';
    if (detailEl) detailEl.innerHTML = '<p class="text-slate-400">加载中...</p>';
    if (metaEl) metaEl.innerHTML = '';

    try {
        const paper = await (await api('GET', `/papers/${id}`)).json();

        // Render meta info badges
        if (metaEl) {
            const badges = [];
            if (paper.year) badges.push(`<span class="inline-block px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 font-semibold">${escapeHtml(String(paper.year))}</span>`);
            if (paper.filename) badges.push(`<span class="inline-block px-2.5 py-1 rounded-full bg-slate-100 text-slate-600">${escapeHtml(paper.filename)}</span>`);
            if (paper.chunk_count) badges.push(`<span class="inline-block px-2.5 py-1 rounded-full bg-purple-50 text-purple-700">${paper.chunk_count} chunks</span>`);
            if (paper.indexed_at) badges.push(`<span class="inline-block px-2.5 py-1 rounded-full bg-green-50 text-green-700">${escapeHtml(paper.indexed_at)}</span>`);
            metaEl.innerHTML = badges.join('');
        }

        // Render sections (full article content organized by section)
        if (detailEl) {
            const sections = paper.sections || [];
            if (sections.length > 0) {
                detailEl.innerHTML = sections.map(s => {
                    const sectionClass = s.level === 'L0' ? 'bg-blue-50 border-blue-100' : 'bg-white border-slate-200';
                    const headingSize = s.level === 'L0' ? 'text-lg' : 'text-base';
                    const paragraphs = s.text.split(/\n{2,}/).filter(p => p.trim());
                    return `
                        <div class="border rounded-2xl p-6 ${sectionClass} space-y-3">
                            <h3 class="font-bold text-slate-800 ${headingSize}">${escapeHtml(s.title)}</h3>
                            ${paragraphs.map(p => `<p class="text-slate-600 leading-loose text-sm">${escapeHtml(p.trim())}</p>`).join('')}
                        </div>`;
                }).join('');
            } else {
                // Fallback: use abstract/full_text
                const content = paper.full_text || paper.abstract || '暂无内容';
                const paragraphs = content.split(/\n{2,}/).filter(p => p.trim());
                detailEl.innerHTML = paragraphs.map(p =>
                    `<p class="text-slate-600 leading-loose">${escapeHtml(p.trim())}</p>`
                ).join('');
            }
        }

        const authorsEl = document.getElementById('detailPaperAuthors');
        if (authorsEl) authorsEl.textContent = authors || '';
    } catch (e) {
        if (abstractEl) abstractEl.textContent = '加载失败';
        if (detailEl) detailEl.innerHTML = '<p class="text-slate-400">加载失败</p>';
    }
    lucide.createIcons();
}

function closePaperDetail() {
    safeClassAction('paperListView', 'remove', 'hidden');
    safeClassAction('paperDetailView', 'add', 'hidden');
}

// ============ Drafts ============
function renderDrafts(sections) {
    const c = document.getElementById('draftList');
    if (!c) return;
    if (!sections || sections.length === 0) {
        c.innerHTML = '<div class="col-span-2 text-center text-slate-400 py-12">暂无章节，点击右上角新建</div>';
        return;
    }
    c.innerHTML = sections.map(s =>
        `<div data-action="openDraft" data-id="${escapeAttr(s.id)}" data-name="${escapeAttr(s.name)}" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm animate__animated animate__fadeIn cursor-pointer">
            <h4 class="font-bold text-slate-800 text-sm mb-2">${escapeHtml(s.name)}</h4>
            <p class="text-[10px] text-slate-400">最后编辑于：刚刚</p>
        </div>`
    ).join('');
    lucide.createIcons();
}

let _draftGenerating = false;
let _progressTimer = null;
let _progressStep = 0;
const _PROGRESS_STEPS = [
    { label: '分析意图', icon: 'brain' },
    { label: '检索知识库', icon: 'search' },
    { label: '调用 Agent 生成', icon: 'sparkles' },
    { label: '标注来源', icon: 'bookmark' },
    { label: '完成', icon: 'check-circle' },
];

function showGenerationProgress(sectionName) {
    _progressStep = 0;
    const overlay = document.getElementById('generationProgress');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    const bar = overlay.querySelector('.gen-progress-bar');
    const stepLabel = overlay.querySelector('.gen-progress-label');
    const stepIcon = overlay.querySelector('.gen-progress-icon');
    const titleEl = overlay.querySelector('.gen-progress-title');
    if (titleEl) titleEl.textContent = `正在生成「${sectionName}」`;
    if (bar) bar.style.width = '5%';
    if (stepLabel) stepLabel.textContent = _PROGRESS_STEPS[0].label;
    if (stepIcon) stepIcon.setAttribute('data-lucide', _PROGRESS_STEPS[0].icon);

    _progressTimer = setInterval(() => {
        _progressStep = Math.min(_progressStep + 1, _PROGRESS_STEPS.length - 2);
        const step = _PROGRESS_STEPS[_progressStep];
        const pct = Math.min(10 + (_progressStep + 1) * 20, 90);
        if (bar) bar.style.width = pct + '%';
        if (stepLabel) stepLabel.textContent = step.label;
        if (stepIcon) {
            stepIcon.setAttribute('data-lucide', step.icon);
            lucide.createIcons();
        }
    }, 4000);
}

function hideGenerationProgress(success = true) {
    if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
    const overlay = document.getElementById('generationProgress');
    if (!overlay) return;
    const bar = overlay.querySelector('.gen-progress-bar');
    const stepLabel = overlay.querySelector('.gen-progress-label');
    const stepIcon = overlay.querySelector('.gen-progress-icon');
    if (success) {
        if (bar) bar.style.width = '100%';
        if (stepLabel) stepLabel.textContent = '完成';
        if (stepIcon) {
            stepIcon.setAttribute('data-lucide', 'check-circle');
            lucide.createIcons();
        }
        setTimeout(() => overlay.classList.add('hidden'), 1200);
    } else {
        overlay.classList.add('hidden');
    }
}

async function confirmCreateDraft() {
    if (_draftGenerating) { showToast('正在生成中，请稍候', 'error'); return; }
    const name = document.getElementById('newDraftTitle').value.trim();
    if (!name) { showToast('请输入章节名称', 'error'); return; }
    if (!currentProjectId) { showToast('请先选择或创建项目', 'error'); return; }
    const style = document.getElementById('draftStyle')?.value || '学术正式';
    const length = parseInt(document.getElementById('draftLength')?.value || '1000');
    const citation = document.getElementById('draftCitation')?.value || '正常';
    const agentEl = document.getElementById('draftAgent');
    const agent = agentEl?.value || 'writer';
    // Get agent prompt from agents array
    const agentObj = (typeof agents !== 'undefined' && agents) ? agents.find(a => a.id === agent) : null;
    const systemPrompt = agentObj?.prompt || '';
    const requirements = document.getElementById('draftRequirements')?.value?.trim() || '';
    toggleModal('newDraftModal');
    _draftGenerating = true;
    showGenerationProgress(name);

    try {
        const result = await (await api('POST', '/sections', {
            project_id: currentProjectId,
            name: name,
            style: style,
            target_length: length,
            citation_density: citation,
            agent: agent,
            system_prompt: systemPrompt,
            requirements: requirements,
        })).json();
        _draftGenerating = false;
        hideGenerationProgress(true);
        showToast('章节生成完成', 'success');
        await loadProjectData();

        // Open editor — try section_id first, then lookup by name
        let sectionId = result.section_id;
        if (!sectionId) {
            const state = await (await api('GET', `/projects/${currentProjectId}/state`)).json();
            const sec = (state.sections_with_id || []).find(s => s.name === name);
            if (sec) sectionId = sec.id;
        }
        if (sectionId) {
            openDraftEditor(sectionId, name);
        } else if (result.content) {
            // Last fallback: show content directly in editor
            currentDraftId = null;
            currentDraftName = name;
            safeClassAction('draftListView', 'add', 'hidden');
            safeClassAction('draftEditor', 'remove', 'hidden');
            document.getElementById('editorTitle').textContent = name;
            document.getElementById('editableArea').innerText = result.content;
            document.getElementById('subChatWindow').innerHTML = '<div class="sub-bubble sub-bubble-ai">协作模式已激活。输入指令来修改章节内容。</div>';
            lucide.createIcons();
        }
    } catch (e) {
        _draftGenerating = false;
        hideGenerationProgress(false);
        showToast('生成失败: ' + e.message, 'error');
    }
}

async function openDraftEditor(id, name) {
    currentDraftId = id;
    currentDraftName = name;
    safeClassAction('draftListView', 'add', 'hidden');
    safeClassAction('draftEditor', 'remove', 'hidden');
    document.getElementById('editorTitle').textContent = name;
    const subWin = document.getElementById('subChatWindow');
    subWin.innerHTML = '<div class="sub-bubble sub-bubble-ai">协作模式已激活。输入指令来修改章节内容。</div>';

    // Load section content
    try {
        const sections = await (await api('GET', `/sections?project_id=${currentProjectId}`)).json();
        const sec = sections.find(s => s.id === id);
        document.getElementById('editableArea').innerText = sec ? sec.content : '';
    } catch (e) {
        document.getElementById('editableArea').innerText = '加载失败';
    }

    // Restore collaborative conversation history (persisted server-side).
    if (id) {
        try {
            const histResp = await api('GET', `/sections/${id}/chats`);
            if (histResp.ok) {
                const histData = await histResp.json();
                const msgs = (histData && histData.messages) || [];
                if (msgs.length > 0) {
                    subWin.innerHTML = msgs.map(m => {
                        const cls = m.role === 'user' ? 'sub-bubble-user' : 'sub-bubble-ai';
                        return `<div class="sub-bubble ${cls}">${escapeHtml(m.content)}</div>`;
                    }).join('');
                    setTimeout(() => { subWin.scrollTop = subWin.scrollHeight; }, 50);
                }
            }
        } catch (histErr) {
            console.warn('Load section chat history failed:', histErr);
        }
    }
    lucide.createIcons();
}

async function clearSectionChats() {
    if (!currentDraftId) {
        showToast('未打开任何章节', 'error');
        return;
    }
    if (!confirm('确定清空「' + currentDraftName + '」的全部协作对话？\n（章节内容本身会保留，只清空对话历史，用于上下文隔离）')) return;
    try {
        const resp = await api('DELETE', `/sections/${currentDraftId}/chats`);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        const subWin = document.getElementById('subChatWindow');
        if (subWin) {
            subWin.innerHTML = '<div class="sub-bubble sub-bubble-ai">协作模式已激活（已清空历史）。输入指令来修改章节内容。</div>';
        }
        showToast(`已清空 ${data.deleted || 0} 条对话`, 'success');
        lucide.createIcons();
    } catch (e) {
        showToast('清空失败: ' + e.message, 'error');
    }
}

function closeDraftEditor() {
    safeClassAction('draftListView', 'remove', 'hidden');
    safeClassAction('draftEditor', 'add', 'hidden');
    loadProjectData();
}

async function handleSendSubChat() {
    const input = document.getElementById('subInput');
    if (!input.value.trim() || !currentProjectId) return;
    const text = input.value;
    input.value = '';

    // Add user bubble
    const win = document.getElementById('subChatWindow');
    win.innerHTML += `<div class="sub-bubble sub-bubble-user">${escapeHtml(text)}</div>`;
    win.scrollTop = win.scrollHeight;

    // Add AI loading bubble
    const aiBubbleId = 'sub-ai-' + Date.now();
    win.innerHTML += `<div id="${aiBubbleId}" class="sub-bubble sub-bubble-ai">思考中...</div>`;
    win.scrollTop = win.scrollHeight;

    try {
        const content = document.getElementById('editableArea').innerText;
        const subBody = {
            message: text,
            project_id: currentProjectId,
            section_name: currentDraftName,
            section_id: currentDraftId || '',
            content: content,
        };
        const activeKey2 = getActiveApiKey();
        if (activeKey2) {
            subBody.api_key = activeKey2.apiKey;
            subBody.base_url = activeKey2.baseUrl;
        }
        const result = await (await api('POST', '/chat/sub', subBody)).json();

        document.getElementById(aiBubbleId).innerHTML = escapeHtml(result.content || '处理完成');

        // Only update the editor area when the backend actually rewrote the
        // section (intent === 'modify'). Q&A / discussion replies (intent ===
        // 'chat') must NOT overwrite the user's draft.
        if (result.intent === 'modify' && result.content && result.type !== 'error') {
            document.getElementById('editableArea').innerText = result.content;
            // Save back
            if (currentDraftId) {
                await api('PUT', `/sections/${currentDraftId}`, { content: result.content });
            }
        }
    } catch (e) {
        document.getElementById(aiBubbleId).textContent = '错误: ' + e.message;
    }
    win.scrollTop = win.scrollHeight;
    lucide.createIcons();
}

async function smartExpand() {
    const content = document.getElementById('editableArea').innerText;
    if (!content || !currentProjectId) return;
    document.getElementById('subInput').value = `请续写「${currentDraftName}」章节，在现有内容基础上扩展`;
    handleSendSubChat();
}

// ============ Chat ============
async function handleSendChat() {
    const input = document.getElementById('chatInput');
    if (!input.value.trim() || chatBusy || !currentProjectId) return;
    const text = input.value;
    input.value = '';
    chatBusy = true;

    appendUserMessage(text);

    const container = document.getElementById('dynamicChatContent');
    const collabId = 'collab-' + Date.now();

    const collabDiv = document.createElement('div');
    collabDiv.className = 'flex gap-4 mb-8 animate__animated animate__fadeInUp';
    collabDiv.innerHTML = `
        ${AI_AVATAR}
        <div class="flex-1 space-y-4">
            <div class="bg-indigo-50 border border-indigo-100 p-6 rounded-3xl rounded-tl-none">
                <div class="flex items-center gap-2 mb-4">
                    <span class="text-[10px] font-bold text-indigo-600 uppercase tracking-widest">Multi-Agent 协作中</span>
                </div>
                <div class="space-y-1 text-xs text-indigo-900/70" id="${collabId}-timeline"></div>
            </div>
            <div id="${collabId}-res" class="bg-white border border-slate-200 p-6 rounded-3xl text-sm leading-relaxed hidden shadow-sm"></div>
        </div>`;
    container.appendChild(collabDiv);
    lucide.createIcons();
    scrollChat();

    // Check for tool trigger words and show tool-invocation-card
    const matchedTool = tools.find(t => t.trigger.split(', ').some(kw => text.includes(kw)));

    try {
        // Attach user API key if available
        const activeKey = getActiveApiKey();
        const selectedModel = document.getElementById('modelSelect')?.value || '';
        const chatBody = { message: text, project_id: currentProjectId };
        if (currentSessionId) {
            chatBody.session_id = currentSessionId;
        }
        if (activeKey) {
            chatBody.api_key = activeKey.apiKey;
            chatBody.base_url = activeKey.baseUrl;
        }
        if (selectedModel) {
            chatBody.model = selectedModel;
        }
        const chatHeaders = { 'Content-Type': 'application/json' };
        if (currentUser && currentUser.token) {
            chatHeaders['Authorization'] = `Bearer ${currentUser.token}`;
        }
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: chatHeaders,
            body: JSON.stringify(chatBody),
        });

        // If a tool was matched, show the invocation card
        if (matchedTool) {
            const toolCard = document.createElement('div');
            toolCard.className = 'tool-invocation-card text-xs animate__animated animate__fadeIn';
            toolCard.innerHTML = `<div class="p-2 bg-indigo-600 text-white rounded-lg"><i data-lucide="terminal" class="w-4 h-4"></i></div><div class="flex-1"><p class="font-bold">Orchestrator: 调用固定工具</p><p class="text-slate-500">Analyst Agent 执行脚本: <b>${escapeHtml(matchedTool.title)}</b></p></div>`;
            container.appendChild(toolCard);
            lucide.createIcons();
            scrollChat();
        }

        if (!response.ok) {
            const errText = await response.text().catch(() => 'Unknown error');
            throw new Error(`Chat request failed: HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let events = [];
        let streamingContent = '';
        let resBox = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer (handle both \n\n and \r\n\r\n)
            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || '';

            for (const part of parts) {
                let eventType = '';
                let data = '';
                for (const line of part.split('\n')) {
                    const trimmed = line.replace(/\r$/, '');
                    if (trimmed.startsWith('event: ')) eventType = trimmed.slice(7);
                    if (trimmed.startsWith('data: ')) data = trimmed.slice(6);
                }
                if (eventType && data) {
                    try { data = JSON.parse(data); } catch { /* keep as string */ }
                    events.push({ type: eventType, data });

                    // Real-time agent timeline in collab bubble
                    if (eventType === 'agent_start' && data.agent) {
                        appendTimelineStep(collabId + '-timeline', data.agent, 'running', data.detail);
                        updateAgentStatus(data.agent, 'RUNNING');
                    }
                    if (eventType === 'agent_end' && data.agent) {
                        updateTimelineStep(collabId + '-timeline', data.agent, 'done', data.detail, data.duration_ms);
                        updateAgentStatus(data.agent, 'READY');
                    }

                    // Session event: save session_id for multi-turn
                    if (eventType === 'session' && data.session_id) {
                        currentSessionId = data.session_id;
                        localStorage.setItem('citewise_session', JSON.stringify(currentSessionId));
                    }

                    // CoVe verification result
                    if (eventType === 'verification') {
                        const collabParent = document.getElementById(collabId + '-res')?.parentElement?.parentElement;
                        if (collabParent) {
                            const coveError = data.error;
                            const score = data.overall_score || 0;
                            const claimCount = data.claim_count || 0;
                            const flaggedCount = data.flagged_count || 0;

                            const coveCard = document.createElement('div');
                            coveCard.className = 'cove-card';

                            if (coveError) {
                                // Verification process failed (API error)
                                coveCard.innerHTML = `
                                    <div class="flex items-center gap-3 mb-2">
                                        <span class="cove-score low"><i data-lucide="alert-triangle" class="w-4 h-4 inline"></i></span>
                                        <div>
                                            <div class="font-bold text-slate-700">事实性验证</div>
                                            <div class="text-amber-600 text-xs">${claimCount > 0 ? `已提取 ${claimCount} 个声明，但` : ''}${escapeHtml(coveError)}</div>
                                            <div class="text-slate-400 text-[10px] mt-1">建议稍后重新提问以触发验证</div>
                                        </div>
                                    </div>`;
                            } else {
                                // Verification succeeded
                                const scoreClass = score > 0.8 ? 'high' : (score > 0.5 ? 'medium' : 'low');
                                let flaggedHtml = '';
                                if (data.flagged_claims && data.flagged_claims.length > 0) {
                                    flaggedHtml = data.flagged_claims.map(f =>
                                        `<div class="cove-flagged-item"><strong>${escapeHtml(f.status)}</strong>: ${escapeHtml(f.claim)}${f.issue ? '<br><span class="text-slate-500">' + escapeHtml(f.issue) + '</span>' : ''}</div>`
                                    ).join('');
                                }
                                coveCard.innerHTML = `
                                    <div class="flex items-center gap-3 mb-2">
                                        <span class="cove-score ${scoreClass}">${(score * 100).toFixed(0)}%</span>
                                        <div>
                                            <div class="font-bold text-slate-700">事实性验证</div>
                                            <div class="text-slate-400">${claimCount} 个声明${flaggedCount > 0 ? '，<span class="text-red-500">' + flaggedCount + ' 个存疑</span>' : '，全部可信'}</div>
                                        </div>
                                    </div>
                                    ${flaggedHtml ? '<details><summary class="cursor-pointer text-xs text-slate-500 font-bold">查看详情</summary>' + flaggedHtml + '</details>' : ''}`;
                            }
                            collabParent.appendChild(coveCard);
                            lucide.createIcons();
                            scrollChat();
                        }
                    }

                    // Token-level streaming: append tokens in real-time
                    if (eventType === 'token' && data.text) {
                        if (!resBox) {
                            resBox = document.getElementById(collabId + '-res');
                            if (resBox) {
                                resBox.classList.remove('hidden');
                                resBox.innerHTML = '';
                            }
                        }
                        if (resBox) {
                            streamingContent += data.text;
                            // Use innerHTML for source-colored display
                            resBox.textContent = streamingContent;
                            scrollChat();
                        }
                    }
                }
            }
        }

        // Process remaining events for final content
        let content = '';
        for (const evt of events) {
            if (evt.type === 'content' && evt.data) {
                content = evt.data.content || '';
            }
            if (evt.type === 'section') {
                showToast(`章节「${evt.data.section_name || ''}」已生成`, 'success');
                loadProjectData();
            }
            if (evt.type === 'error') {
                showToast('错误: ' + (evt.data.message || '未知错误'), 'error');
            }
        }

        // Final render with source annotations
        if (content && resBox) {
            await streamCategorizedText(resBox, content);
        } else if (!content && streamingContent && resBox) {
            // Fallback: if no final content event, use streamed tokens
            resBox.textContent = streamingContent;
        }
    } catch (e) {
        showToast('请求失败: ' + e.message, 'error');
    }

    chatBusy = false;
}

// ---- Agent status in left sidebar ----
function updateAgentStatus(agentName, status) {
    const mapping = {
        'Supervisor': null,
        'Researcher': 'research',
        'research': 'research',
        'Responder': null,
        'Writer': 'writing',
        'writing': 'writing',
        'Analyst': 'analyst',
        'analyst': 'analyst'
    };
    const agentId = mapping[agentName];
    if (!agentId) return;
    const agent = agents.find(a => a.id === agentId);
    if (agent) {
        agent.status = status;
        renderAgentStatus();
    }
}

// ---- Agent Timeline helpers (inline collab bubble) ----
function appendTimelineStep(containerId, agent, status, detail) {
    const c = document.getElementById(containerId);
    if (!c) return;
    const stepId = containerId + '-' + agent;
    if (document.getElementById(stepId)) return; // already exists
    const colors = {
        Supervisor: 'border-indigo-500', Researcher: 'border-blue-500',
        Responder: 'border-violet-500', Writer: 'border-amber-500', Analyst: 'border-emerald-500',
    };
    const cls = status === 'running' ? 'collab-step active' : 'collab-step';
    const div = document.createElement('div');
    div.id = stepId;
    div.className = `${cls}`;
    div.style.borderLeftColor = (colors[agent] || 'border-slate-400').replace('border-', '');
    div.textContent = `${agent}: ${detail || '处理中...'}`;
    c.appendChild(div);
}

function updateTimelineStep(containerId, agent, status, detail, durationMs) {
    const stepId = containerId + '-' + agent;
    const el = document.getElementById(stepId);
    if (!el) {
        appendTimelineStep(containerId, agent, status, detail);
        return;
    }
    el.className = 'collab-step completed';
    el.textContent = `${agent}: ${detail || '完成'}${durationMs ? ` (${durationMs}ms)` : ''}`;
}

async function streamCategorizedText(target, fullText) {
    // Parse [KB]/[WEB]/[AI] source annotations from backend
    const parts = [];
    const lines = fullText.split('\n');
    let currentType = 'ai';
    let currentText = '';

    for (const line of lines) {
        if (line.startsWith('[KB]')) {
            if (currentText.trim()) parts.push({ type: currentType, text: currentText });
            currentType = 'kb';
            currentText = line.slice(4).trimStart() + '\n';
        } else if (line.startsWith('[WEB]')) {
            if (currentText.trim()) parts.push({ type: currentType, text: currentText });
            currentType = 'web';
            currentText = line.slice(5).trimStart() + '\n';
        } else if (line.startsWith('[AI]')) {
            if (currentText.trim()) parts.push({ type: currentType, text: currentText });
            currentType = 'ai';
            currentText = line.slice(4).trimStart() + '\n';
        } else {
            currentText += line + '\n';
        }
    }
    if (currentText.trim()) parts.push({ type: currentType, text: currentText });
    if (parts.length === 0) parts.push({ type: 'ai', text: fullText });

    // Streaming phase: show plain text character by character
    for (const part of parts) {
        const span = document.createElement('span');
        span.className = `txt-${part.type} animate__animated animate__fadeIn`;
        target.appendChild(span);
        const chars = part.text.trim();
        for (let i = 0; i < chars.length; i++) {
            span.textContent += chars[i];
            if (i % 3 === 0) scrollChat();
            await new Promise(r => setTimeout(r, 8));
        }
        await new Promise(r => setTimeout(r, 50));
    }

    // Post-stream: replace with Markdown-rendered content
    const renderedParts = parts.map(p => {
        const mdHtml = renderMarkdown(p.text);
        return `<span class="txt-${p.type}">${mdHtml}</span>`;
    }).join('');
    target.innerHTML = renderedParts;
    target.classList.add('md-render');
    scrollChat();
}

function parseSourceAnnotations(fullText) {
    const parts = [];
    const lines = fullText.split('\n');
    let currentType = 'ai';
    let currentText = '';
    for (const line of lines) {
        if (line.startsWith('[KB]')) {
            if (currentText.trim()) parts.push({ type: currentType, text: currentText });
            currentType = 'kb';
            currentText = line.slice(4).trimStart() + '\n';
        } else if (line.startsWith('[WEB]')) {
            if (currentText.trim()) parts.push({ type: currentType, text: currentText });
            currentType = 'web';
            currentText = line.slice(5).trimStart() + '\n';
        } else if (line.startsWith('[AI]')) {
            if (currentText.trim()) parts.push({ type: currentType, text: currentText });
            currentType = 'ai';
            currentText = line.slice(4).trimStart() + '\n';
        } else {
            currentText += line + '\n';
        }
    }
    if (currentText.trim()) parts.push({ type: currentType, text: currentText });
    if (parts.length === 0) parts.push({ type: 'ai', text: fullText });
    return parts;
}

function renderCategorizedText(target, fullText) {
    const parts = parseSourceAnnotations(fullText);
    const renderedParts = parts.map(p => {
        const mdHtml = renderMarkdown(p.text);
        return `<span class="txt-${p.type}">${mdHtml}</span>`;
    }).join('');
    target.innerHTML = renderedParts;
    target.classList.add('md-render');
}

function renderMarkdown(text) {
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
        // Fallback: escape HTML if libraries not loaded
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    try {
        return DOMPurify.sanitize(marked.parse(text.trim()));
    } catch (e) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

function appendUserMessage(text) {
    const c = document.getElementById('dynamicChatContent');
    const d = document.createElement('div');
    d.className = 'flex gap-4 flex-row-reverse mb-8 animate__animated animate__fadeInUp';
    d.innerHTML = `
        ${USER_AVATAR}
        <div class="bg-blue-600 text-white p-5 rounded-3xl rounded-tr-none text-sm max-w-[80%] shadow-md">${escapeHtml(text)}</div>`;
    c.appendChild(d);
    lucide.createIcons();
    scrollChat();
}

// ---- Tab switching for combined views ----
function switchExtensionTab(tabId) {
    document.getElementById('skillTab').classList.toggle('hidden', tabId !== 'skillTab');
    document.getElementById('toolTab').classList.toggle('hidden', tabId !== 'toolTab');
    document.getElementById('extSkillTabBtn').classList.toggle('active', tabId === 'skillTab');
    document.getElementById('extToolTabBtn').classList.toggle('active', tabId === 'toolTab');
    document.getElementById('extSkillAction').classList.toggle('hidden', tabId !== 'skillTab');
    document.getElementById('extToolAction').classList.toggle('hidden', tabId !== 'toolTab');
    // Render content
    if (tabId === 'skillTab') {
        const c = document.getElementById('extensionSkillList');
        if (c) renderSkillListInto(c);
    } else {
        const c = document.getElementById('extensionToolList');
        if (c) renderToolListInto(c);
    }
    lucide.createIcons();
}

function switchAgentHubTab(tabId) {
    document.getElementById('agentConfigTab').classList.toggle('hidden', tabId !== 'agentConfigTab');
    document.getElementById('agentEvalTab').classList.toggle('hidden', tabId !== 'agentEvalTab');
    document.getElementById('ahConfigTabBtn').classList.toggle('active', tabId === 'agentConfigTab');
    document.getElementById('ahEvalTabBtn').classList.toggle('active', tabId !== 'agentConfigTab');
    document.getElementById('ahConfigAction').classList.toggle('hidden', tabId !== 'agentConfigTab');
    if (tabId === 'agentConfigTab') {
        const c = document.getElementById('hubAgentList');
        if (c) renderAgentCardsInto(c);
    } else {
        loadEvalDashboardInto('hubEvalContent');
    }
    lucide.createIcons();
}

function renderSkillListInto(container) {
    if (!container) return;
    container.innerHTML = skills.map(s =>
        `<div onclick="openSkillDetail(${s.id})" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm group animate__animated animate__fadeIn cursor-pointer relative">
            <button onclick="event.stopPropagation(); deleteSkill(${s.id}); switchExtensionTab('skillTab')" class="absolute top-3 right-3 w-6 h-6 rounded-full bg-red-50 text-red-400 hover:bg-red-100 hover:text-red-600 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all text-xs font-bold">&times;</button>
            <div class="flex justify-between items-start mb-4">
                <div class="p-2 bg-amber-50 text-amber-600 rounded-lg"><i data-lucide="${s.icon}" class="w-5 h-5"></i></div>
                <span class="text-[7px] uppercase font-bold text-blue-500 mt-2">On ${escapeHtml(s.agent)} Agent</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm mb-1">${escapeHtml(s.title)}</h4>
            <p class="text-[10px] text-slate-500">${escapeHtml(s.desc)}</p>
        </div>`
    ).join('');
}

function renderToolListInto(container) {
    if (!container) return;
    container.innerHTML = tools.map(t =>
        `<div onclick="openToolDetail(${t.id})" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm group animate__animated animate__fadeIn cursor-pointer relative">
            <button onclick="event.stopPropagation(); deleteTool(${t.id}); switchExtensionTab('toolTab')" class="absolute top-3 right-3 w-6 h-6 rounded-full bg-red-50 text-red-400 hover:bg-red-100 hover:text-red-600 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all text-xs font-bold">&times;</button>
            <div class="flex justify-between mb-4">
                <div class="p-2 bg-blue-50 text-blue-600 rounded-lg"><i data-lucide="${t.icon}" class="w-5 h-5"></i></div>
                <span class="px-2 py-1 bg-slate-50 text-slate-400 text-[8px] font-bold rounded">Fixed</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm mb-1">${escapeHtml(t.title)}</h4>
            <p class="text-[10px] text-slate-500">${escapeHtml(t.desc)}</p>
            <div class="mt-4 pt-3 border-t border-slate-50 text-[8px] text-slate-400 font-bold uppercase">指令词: ${escapeHtml(t.trigger)}</div>
        </div>`
    ).join('');
}

function renderAgentCardsInto(container) {
    if (!container) return;
    container.innerHTML = agents.map(a => {
        const assignedSkills = skills.filter(s => s.agent === a.id);
        return `<div onclick="openAgentDetail('${a.id}')" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm cursor-pointer hover:border-indigo-200 transition-all group relative">
            <button onclick="event.stopPropagation(); deleteAgent('${a.id}'); switchAgentHubTab('agentConfigTab')" class="absolute top-3 right-3 w-6 h-6 rounded-full bg-red-50 text-red-400 hover:bg-red-100 hover:text-red-600 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all text-xs font-bold">&times;</button>
            <div class="flex justify-between items-start mb-4">
                <div class="p-3 bg-${a.color}-50 text-${a.color}-600 rounded-xl"><i data-lucide="${a.icon}" class="w-6 h-6"></i></div>
                <span class="text-[8px] font-bold uppercase px-2 py-1 rounded ${a.status === 'RUNNING' ? 'bg-amber-50 text-amber-600' : 'bg-green-50 text-green-600'}">${a.status}</span>
            </div>
            <h4 class="font-bold text-slate-800 text-base mb-1">${escapeHtml(a.name)}</h4>
            <p class="text-xs text-slate-500 mb-3">${escapeHtml(a.description || '自定义 Agent')}</p>
            <div class="flex items-center gap-2 text-[10px] text-slate-400"><i data-lucide="zap" class="w-3 h-3"></i><span>${assignedSkills.length} 个 Skill</span></div>
        </div>`;
    }).join('');
}

async function loadEvalDashboardInto(containerId) {
    const container = document.getElementById(containerId);
    if (!container || !currentProjectId) return;
    container.innerHTML = '<div class="text-center text-slate-400 py-12">加载中...</div>';
    try {
        const days = 7;
        const [metrics, trends] = await Promise.all([
            (await api('GET', `/eval/metrics?days=${days}&project_id=${currentProjectId}`)).json(),
            (await api('GET', `/eval/trends?days=${days}&project_id=${currentProjectId}`)).json(),
        ]);
        container.innerHTML = `
            <div class="grid grid-cols-5 gap-4">
                <div class="bg-white border border-slate-200 rounded-2xl p-5 text-center">
                    <div class="text-2xl font-bold ${metrics.success_rate >= 85 ? 'text-emerald-600' : 'text-red-600'}">${metrics.success_rate}%</div>
                    <div class="text-[10px] text-slate-400 font-bold mt-1">任务成功率</div>
                </div>
                <div class="bg-white border border-slate-200 rounded-2xl p-5 text-center">
                    <div class="text-2xl font-bold text-blue-600">${Math.round(metrics.avg_response_time_ms)}ms</div>
                    <div class="text-[10px] text-slate-400 font-bold mt-1">平均响应</div>
                </div>
                <div class="bg-white border border-slate-200 rounded-2xl p-5 text-center">
                    <div class="text-2xl font-bold ${metrics.hallucination_rate <= 10 ? 'text-emerald-600' : 'text-red-600'}">${metrics.hallucination_rate}%</div>
                    <div class="text-[10px] text-slate-400 font-bold mt-1">幻觉率</div>
                </div>
                <div class="bg-white border border-slate-200 rounded-2xl p-5 text-center">
                    <div class="text-2xl font-bold text-purple-600">${metrics.success_count || 0}</div>
                    <div class="text-[10px] text-slate-400 font-bold mt-1">成功任务</div>
                </div>
                <div class="bg-white border border-slate-200 rounded-2xl p-5 text-center">
                    <div class="text-2xl font-bold text-slate-700">${metrics.total_tasks || 0}</div>
                    <div class="text-[10px] text-slate-400 font-bold mt-1">总任务数</div>
                </div>
            </div>
            <div id="hubEvalSuggestions" class="space-y-2"></div>`;
        lucide.createIcons();
    } catch (e) {
        container.innerHTML = '<div class="text-center text-slate-400 py-12">加载评估数据失败</div>';
    }
}

// ---- Material Collection (Reading → Writing Bridge) ----
function addCurrentPaperToMaterials() {
    const title = document.getElementById('detailPaperDisplayTitle')?.textContent || '';
    const content = document.getElementById('paperDetailContent')?.innerText || '';
    if (!content.trim()) {
        showToast('暂无可添加的内容', 'error');
        return;
    }
    addToMaterials('paper', content, title);
}

function addChatResponseToMaterials(responseElement) {
    const content = responseElement?.innerText || responseElement?.textContent || '';
    if (!content.trim()) return;
    addToMaterials('chat', content, '');
}

// ---- Knowledge Map (D3.js Force-directed Graph) ----
async function loadKnowledgeMap() {
    if (!currentProjectId) return;
    const loading = document.getElementById('knowledgeMapLoading');
    const svg = document.getElementById('knowledgeMapSvg');
    if (!svg || !loading) return;

    loading.textContent = '加载中...';
    loading.classList.remove('hidden');

    // 等待 DOM 布局就绪（switchView 刚将容器从 display:none 切为 flex）
    await new Promise(r => requestAnimationFrame(r));

    try {
        const data = await (await api('GET', `/knowledge-map?project_id=${currentProjectId}`)).json();
        if (!data.nodes || data.nodes.length === 0) {
            loading.textContent = '暂无文献，请先上传 PDF';
            return;
        }
        loading.classList.add('hidden');
        renderKnowledgeMap(data);
    } catch (e) {
        loading.textContent = '加载失败: ' + e.message;
    }
}

function renderKnowledgeMap(data) {
    const svg = d3.select('#knowledgeMapSvg');
    svg.selectAll('*').remove();

    const container = document.getElementById('knowledgeMapContainer');
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;

    svg.attr('viewBox', [0, 0, width, height]);

    // Color scale by year
    const years = data.nodes.map(n => parseInt(n.year) || 2020);
    const minYear = Math.min(...years);
    const maxYear = Math.max(...years);
    const colorScale = d3.scaleSequential(d3.interpolateBlues)
        .domain([minYear - 2, maxYear + 2]);

    // Size scale by chunk count
    const maxChunks = Math.max(...data.nodes.map(n => n.chunk_count || 1), 1);
    const sizeScale = d3.scaleSqrt().domain([0, maxChunks]).range([15, 40]);

    // Build links
    const nodeMap = {};
    data.nodes.forEach(n => nodeMap[n.id] = n);
    const links = (data.edges || []).filter(e => nodeMap[e.source] && nodeMap[e.target]);

    // Simulation
    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(d => sizeScale(d.chunk_count || 1) + 5));

    // Links
    const link = svg.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', d => d.type === 'citation' ? '#f59e0b' : '#3b82f6')
        .attr('stroke-width', d => d.type === 'citation' ? 2 : Math.max(1, d.weight * 3))
        .attr('stroke-dasharray', d => d.type === 'citation' ? '5,5' : 'none')
        .attr('stroke-opacity', 0.6);

    // Nodes
    const node = svg.append('g')
        .selectAll('g')
        .data(data.nodes)
        .join('g')
        .attr('cursor', 'pointer')
        .call(d3.drag()
            .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    node.append('circle')
        .attr('r', d => sizeScale(d.chunk_count || 1))
        .attr('fill', d => colorScale(parseInt(d.year) || 2020))
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .on('click', (event, d) => openPaperDetail(d.id, d.title, d.authors));

    node.append('text')
        .text(d => (d.title || 'Untitled').substring(0, 15) + (d.title && d.title.length > 15 ? '...' : ''))
        .attr('dy', d => sizeScale(d.chunk_count || 1) + 14)
        .attr('text-anchor', 'middle')
        .attr('font-size', '10px')
        .attr('fill', '#64748b')
        .attr('font-weight', '600');

    // Title tooltip on hover
    node.append('title')
        .text(d => `${d.title}\n作者: ${d.authors}\n年份: ${d.year}\nChunks: ${d.chunk_count}`);

    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
}
function addToMaterials(source, content, paperTitle) {
    if (!content || !content.trim()) return;
    const material = {
        id: Date.now(),
        source: source, // 'paper' or 'chat'
        content: content.substring(0, 500),
        paperTitle: paperTitle || '',
        project_id: currentProjectId,
        addedAt: new Date().toLocaleString(),
    };
    researchMaterials.push(material);
    saveMaterialsToStorage();
    showToast('已添加到写作素材', 'success');
}

function removeFromMaterials(id) {
    researchMaterials = researchMaterials.filter(m => m.id !== id);
    saveMaterialsToStorage();
    renderMaterialsPanel();
}

function insertMaterialToEditor(id) {
    const material = researchMaterials.find(m => m.id === id);
    if (!material) return;
    const editor = document.getElementById('editableArea');
    if (editor) {
        const current = editor.innerText;
        editor.innerText = current + '\n\n' + material.content;
        // Save back
        if (currentDraftId) {
            api('PUT', `/sections/${currentDraftId}`, { content: editor.innerText });
        }
        showToast('素材已插入到章节', 'success');
    }
}

function saveMaterialsToStorage() {
    const key = `citewise_materials_${currentProjectId || 'default'}`;
    localStorage.setItem(key, JSON.stringify(researchMaterials));
}

function loadMaterialsFromStorage() {
    const key = `citewise_materials_${currentProjectId || 'default'}`;
    const saved = localStorage.getItem(key);
    if (saved) {
        try { researchMaterials = JSON.parse(saved); } catch { researchMaterials = []; }
    } else {
        researchMaterials = [];
    }
}

function renderMaterialsPanel() {
    const panel = document.getElementById('materialsPanel');
    if (!panel) return;
    // Update count
    const countEl = document.getElementById('materialCount');
    if (countEl) countEl.textContent = researchMaterials.length;
    if (researchMaterials.length === 0) {
        panel.innerHTML = '<div class="text-center text-slate-400 py-8 text-xs">暂无素材，从文献详情或聊天中添加</div>';
        return;
    }
    panel.innerHTML = researchMaterials.map(m => `
        <div class="p-3 bg-white border border-slate-100 rounded-xl space-y-2 animate__animated animate__fadeIn">
            <div class="flex items-center justify-between">
                <span class="text-[9px] font-bold ${m.source === 'paper' ? 'text-blue-500' : 'text-indigo-500'} uppercase">${m.source === 'paper' ? '来自文献' : '来自对话'}</span>
                <button onclick="removeFromMaterials(${m.id})" class="text-slate-300 hover:text-red-500"><i data-lucide="x" class="w-3 h-3"></i></button>
            </div>
            <p class="text-xs text-slate-600 leading-relaxed">${escapeHtml(m.content.substring(0, 100))}${m.content.length > 100 ? '...' : ''}</p>
            ${m.paperTitle ? `<p class="text-[9px] text-slate-400">来源: ${escapeHtml(m.paperTitle)}</p>` : ''}
            <button onclick="insertMaterialToEditor(${m.id})" class="w-full py-1.5 bg-indigo-50 text-indigo-600 rounded-lg text-[10px] font-bold hover:bg-indigo-100 transition-all">插入到章节</button>
        </div>
    `).join('');
    lucide.createIcons();
}

function toggleMaterialsPanel() {
    const panel = document.getElementById('materialsPanel');
    const toggle = document.getElementById('materialsToggle');
    if (!panel || !toggle) return;
    panel.classList.toggle('hidden');
    toggle.classList.toggle('active');
    if (!panel.classList.contains('hidden')) {
        renderMaterialsPanel();
    }
}

// ---- Literature Recommendations ----
async function loadRecommendations() {
    const loading = document.getElementById('recommendLoading');
    const empty = document.getElementById('recommendEmpty');
    const error = document.getElementById('recommendError');
    const grid = document.getElementById('recommendGrid');
    if (!loading || !grid) return;

    if (!currentProjectId) {
        empty.classList.remove('hidden');
        loading.classList.add('hidden');
        error.classList.add('hidden');
        grid.classList.add('hidden');
        return;
    }

    loading.classList.remove('hidden');
    empty.classList.add('hidden');
    error.classList.add('hidden');
    grid.classList.add('hidden');

    // Friendly "still working" hint — backend has a 12s hard timeout, so if
    // we're still waiting after 4s, tell the user instead of looking frozen.
    const slowTimer = setTimeout(() => {
        if (!loading.classList.contains('hidden')) {
            loading.textContent = '正在聚合多源推荐，请稍候...';
        }
    }, 4000);

    try {
        const resp = await api('GET', `/recommendations?project_id=${currentProjectId}&top_k=5`);
        const data = await resp.json();
        clearTimeout(slowTimer);
        loading.textContent = '加载中...';
        loading.classList.add('hidden');

        if (!data.recommendations || data.recommendations.length === 0) {
            empty.classList.remove('hidden');
            return;
        }

        renderRecommendations(data.recommendations);
    } catch (e) {
        clearTimeout(slowTimer);
        loading.textContent = '加载中...';
        loading.classList.add('hidden');
        error.classList.remove('hidden');
        document.getElementById('recommendErrorMsg').textContent = '加载失败: ' + e.message;
    }
}

function renderRecommendations(recs) {
    const grid = document.getElementById('recommendGrid');
    const empty = document.getElementById('recommendEmpty');
    if (!grid) return;

    empty.classList.add('hidden');
    grid.classList.remove('hidden');
    grid.innerHTML = '';

    recs.forEach(rec => {
        const scorePercent = Math.round(rec.similarity_score * 100);
        const scoreColor = scorePercent >= 70 ? 'text-emerald-600 bg-emerald-50' :
                           scorePercent >= 40 ? 'text-amber-600 bg-amber-50' :
                           'text-slate-500 bg-slate-50';

        // Source type detection:
        //   external_url present      → external web resource (click opens URL)
        //   recommended_paper_id starts with 'paper_'  → local uploaded paper
        const isExternal = !!rec.external_url;
        const isLocal = !isExternal
            && typeof rec.recommended_paper_id === 'string'
            && rec.recommended_paper_id.startsWith('paper_');
        const sourceBadge = isExternal
            ? '<span class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-600"><i data-lucide="globe" class="w-3 h-3"></i>外部</span>'
            : isLocal
                ? '<span class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700"><i data-lucide="file-text" class="w-3 h-3"></i>本地文献</span>'
                : '<span class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-500"><i data-lucide="book" class="w-3 h-3"></i>相关</span>';

        // Click behaviour: external → open URL; local → open paper detail;
        // neither → no click (just display).
        const card = document.createElement('div');
        const clickable = isExternal || isLocal;
        card.className = `interactive-card bg-white border border-slate-100 rounded-2xl shadow-sm hover:shadow-md transition-all p-5 space-y-3 ${clickable ? 'cursor-pointer hover:border-indigo-200 hover:bg-indigo-50/30' : 'cursor-default'}`;
        if (isExternal) {
            const url = rec.external_url;
            card.onclick = (ev) => {
                ev.preventDefault();
                window.open(url, '_blank', 'noopener');
            };
        } else if (isLocal) {
            const pid = rec.recommended_paper_id;
            const ptitle = rec.recommended_paper_title || '';
            card.onclick = (ev) => {
                ev.preventDefault();
                openPaperDetail(pid, ptitle, '');
            };
        }

        card.innerHTML = `
            <div class="flex items-start justify-between gap-2">
                <h4 class="font-bold text-slate-800 text-sm leading-snug line-clamp-2 flex-1">${escapeHtml(rec.recommended_paper_title || '未知标题')}</h4>
                <span class="shrink-0 text-[10px] font-bold px-2 py-1 rounded-lg ${scoreColor}">${scorePercent}%</span>
            </div>
            <div class="flex items-center gap-2 flex-wrap text-[11px] text-slate-400">
                ${sourceBadge}
                ${rec.recommended_paper_authors ? `<span class="truncate">${escapeHtml(rec.recommended_paper_authors)}</span>` : ''}
                ${rec.recommended_paper_year ? `<span>· ${escapeHtml(String(rec.recommended_paper_year))}</span>` : ''}
            </div>
            <p class="text-[11px] text-slate-500 leading-relaxed">${escapeHtml(rec.recommendation_reason || '')}</p>
            ${isExternal
                ? `<div class="inline-flex items-center gap-1 text-[10px] text-indigo-600"><i data-lucide="external-link" class="w-3 h-3"></i> 点击卡片打开网页</div>`
                : isLocal
                    ? `<div class="inline-flex items-center gap-1 text-[10px] text-emerald-600"><i data-lucide="book-open" class="w-3 h-3"></i> 点击卡片打开文献详情</div>`
                    : ''
            }
            <div class="pt-1 border-t border-slate-50">
                <span class="text-[10px] text-slate-300">${rec.source_paper_title ? '源自: ' + escapeHtml(truncate(rec.source_paper_title, 30)) : '外部文献推荐'}</span>
            </div>
        `;
        grid.appendChild(card);
    });
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.slice(0, len) + '...' : str;
}

// ============ Submit Functions (Journal Recommendation + Format Check) ============

let currentFormatChecklist = [];

function switchSubmitTab(tabId) {
    const journalTab = document.getElementById('journalTab');
    const formatTab = document.getElementById('formatTab');
    const journalBtn = document.getElementById('submitJournalTabBtn');
    const formatBtn = document.getElementById('submitFormatTabBtn');

    if (tabId === 'journalTab') {
        journalTab.classList.remove('hidden');
        formatTab.classList.add('hidden');
        journalBtn.classList.add('active');
        formatBtn.classList.remove('active');
    } else {
        journalTab.classList.add('hidden');
        formatTab.classList.remove('hidden');
        journalBtn.classList.remove('active');
        formatBtn.classList.add('active');
    }
    lucide.createIcons();
}

async function loadJournalRecommendations() {
    if (!currentProjectId) {
        showToast('请先选择项目', 'error');
        return;
    }

    const loading = document.getElementById('journalLoading');
    const empty = document.getElementById('journalEmpty');
    const grid = document.getElementById('journalGrid');
    const error = document.getElementById('journalError');
    const action = document.getElementById('journalAction');

    loading.classList.remove('hidden');
    empty.classList.add('hidden');
    grid.classList.add('hidden');
    error.classList.add('hidden');
    action.classList.add('hidden');

    try {
        const data = await (await api('POST', '/submit/recommend', {
            project_id: currentProjectId
        })).json();

        loading.classList.add('hidden');

        if (data.journals && data.journals.length > 0) {
            renderJournalCards(data.journals);
            action.classList.remove('hidden');
        } else {
            empty.classList.remove('hidden');
            empty.querySelector('p').textContent = data.error || '未找到匹配期刊，请先上传文献并生成章节';
        }
    } catch (e) {
        loading.classList.add('hidden');
        error.classList.remove('hidden');
        document.getElementById('journalErrorMsg').textContent = e.message || '请求失败';
    }
}

function renderJournalCards(journals) {
    const grid = document.getElementById('journalGrid');
    grid.classList.remove('hidden');
    grid.innerHTML = '';

    const levelColors = {
        'SCI-Q1': 'bg-emerald-100 text-emerald-700',
        'SCI-Q2': 'bg-blue-100 text-blue-700',
        'SCI-Q3': 'bg-cyan-100 text-cyan-700',
        'SCI-Q4': 'bg-teal-100 text-teal-700',
        'SCI': 'bg-indigo-100 text-indigo-700',
        'EI': 'bg-amber-100 text-amber-700',
        'CSSCI': 'bg-purple-100 text-purple-700',
        '北大核心': 'bg-rose-100 text-rose-700',
        'CSCD': 'bg-sky-100 text-sky-700',
    };

    journals.forEach((j, idx) => {
        const score = j.match_score || 0;
        const scoreColor = score >= 80 ? 'bg-emerald-500' : score >= 60 ? 'bg-blue-500' : score >= 40 ? 'bg-amber-500' : 'bg-slate-400';
        const levelBadge = levelColors[j.level] || 'bg-slate-100 text-slate-600';

        const card = document.createElement('div');
        card.className = 'interactive-card bg-white border border-slate-100 rounded-2xl shadow-sm hover:shadow-md transition-all p-5 space-y-3 cursor-default';
        card.innerHTML = `
            <div class="flex items-start justify-between gap-2">
                <h4 class="font-bold text-slate-800 text-sm leading-snug line-clamp-2 flex-1">${escapeHtml(j.name || '未知期刊')}</h4>
                <span class="shrink-0 text-[10px] font-bold px-2 py-1 rounded-lg ${levelBadge}">${escapeHtml(j.level || '未知')}</span>
            </div>
            ${j.publisher ? `<p class="text-[11px] text-slate-400">${escapeHtml(j.publisher)}</p>` : ''}
            <div class="flex items-center gap-3">
                <div class="flex-1 bg-slate-100 rounded-full h-1.5">
                    <div class="${scoreColor} h-1.5 rounded-full transition-all" style="width: ${score}%"></div>
                </div>
                <span class="text-[10px] font-bold text-slate-500">${score}%</span>
            </div>
            <p class="text-[11px] text-slate-500 leading-relaxed">${escapeHtml(j.match_reason || '')}</p>
            <div class="flex items-center gap-3 text-[10px] text-slate-400 pt-1 border-t border-slate-50">
                ${j.impact_factor && j.impact_factor !== 'N/A' ? `<span>IF: ${escapeHtml(String(j.impact_factor))}</span>` : ''}
                ${j.review_cycle && j.review_cycle !== 'N/A' ? `<span>周期: ${escapeHtml(j.review_cycle)}</span>` : ''}
                ${j.acceptance_rate && j.acceptance_rate !== 'N/A' ? `<span>录用率: ${escapeHtml(String(j.acceptance_rate))}</span>` : ''}
            </div>
            ${j.submission_url && j.submission_url !== 'N/A' && /^https?:\/\//i.test(j.submission_url) ? `
            <a href="${escapeAttr(j.submission_url)}" target="_blank" class="inline-flex items-center gap-1 text-[10px] font-bold text-indigo-600 hover:underline mt-1">
                <i data-lucide="external-link" class="w-3 h-3"></i> 投稿系统
            </a>` : ''}
        `;
        grid.appendChild(card);
    });
    lucide.createIcons();
}

async function runFormatCheck() {
    if (!currentProjectId) {
        showToast('请先选择项目', 'error');
        return;
    }

    const journalName = document.getElementById('formatJournalInput').value.trim();
    if (!journalName) {
        showToast('请输入目标期刊名称', 'error');
        return;
    }

    const loading = document.getElementById('formatLoading');
    const result = document.getElementById('formatResult');
    const error = document.getElementById('formatError');
    const btn = document.getElementById('formatCheckBtn');

    loading.classList.remove('hidden');
    result.classList.add('hidden');
    error.classList.add('hidden');
    btn.disabled = true;

    try {
        const data = await (await api('POST', '/submit/format-check', {
            project_id: currentProjectId,
            journal_name: journalName
        })).json();

        loading.classList.add('hidden');

        if (data.checklist && data.checklist.length > 0) {
            currentFormatChecklist = data.checklist;
            renderFormatChecklist(data);
        } else {
            error.classList.remove('hidden');
            document.getElementById('formatErrorMsg').textContent = data.error || '未获取到格式要求，请检查期刊名称';
        }
    } catch (e) {
        loading.classList.add('hidden');
        error.classList.remove('hidden');
        document.getElementById('formatErrorMsg').textContent = e.message || '请求失败';
    } finally {
        btn.disabled = false;
    }
}

function renderFormatChecklist(data) {
    const container = document.getElementById('formatResult');
    container.classList.remove('hidden');
    container.innerHTML = '';

    // Summary card
    if (data.requirements_summary) {
        const summaryCard = document.createElement('div');
        summaryCard.className = 'bg-indigo-50 border border-indigo-100 rounded-2xl p-5';
        summaryCard.innerHTML = `
            <div class="flex items-center gap-2 mb-2">
                <i data-lucide="info" class="w-4 h-4 text-indigo-500"></i>
                <span class="text-xs font-bold text-indigo-700">${escapeHtml(data.journal_name || '')} 格式要求概要</span>
            </div>
            <p class="text-xs text-indigo-600 leading-relaxed">${escapeHtml(data.requirements_summary)}</p>
        `;
        container.appendChild(summaryCard);
    }

    const severityStyles = {
        'required': 'border-l-red-400 bg-red-50/30',
        'recommended': 'border-l-amber-400 bg-amber-50/20',
        'optional': 'border-l-slate-300 bg-slate-50/30',
    };
    const severityLabels = {
        'required': '必须',
        'recommended': '建议',
        'optional': '可选',
    };
    const severityBadgeColors = {
        'required': 'bg-red-100 text-red-600',
        'recommended': 'bg-amber-100 text-amber-600',
        'optional': 'bg-slate-100 text-slate-500',
    };
    const categoryIcons = {
        'structure': 'layout',
        'formatting': 'type',
        'citation': 'quote',
        'length': 'ruler',
        'language': 'globe',
        'figures': 'image',
        'abstract': 'file-text',
    };

    const form = document.createElement('div');
    form.className = 'space-y-3';
    form.id = 'formatChecklistForm';

    data.checklist.forEach((item, idx) => {
        const row = document.createElement('div');
        const borderStyle = severityStyles[item.severity] || severityStyles['optional'];
        row.className = `border-l-4 ${borderStyle} rounded-xl p-4 flex items-start gap-3`;
        row.innerHTML = `
            <input type="checkbox" class="format-check-item mt-1 shrink-0 w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" data-index="${idx}" checked>
            <div class="flex-1 space-y-2">
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-[10px] font-bold px-2 py-0.5 rounded ${severityBadgeColors[item.severity] || 'bg-slate-100 text-slate-500'}">${severityLabels[item.severity] || item.severity}</span>
                    <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-600">${escapeHtml(item.category || '')}</span>
                    <span class="text-xs font-bold text-slate-700">${escapeHtml(item.description || '')}</span>
                </div>
                ${item.current_state ? `<p class="text-[11px] text-slate-400"><span class="font-bold">当前状态:</span> ${escapeHtml(item.current_state)}</p>` : ''}
                <p class="text-[11px] text-blue-600"><span class="font-bold">建议:</span> ${escapeHtml(item.suggestion || '')}</p>
            </div>
        `;
        form.appendChild(row);
    });
    container.appendChild(form);

    // Apply button
    const applySection = document.createElement('div');
    applySection.className = 'flex items-center justify-between pt-2';
    applySection.innerHTML = `
        <label class="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" id="formatSelectAll" checked onchange="toggleAllFormatChecks(this.checked)" class="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500">
            全选/取消全选
        </label>
        <button onclick="applySelectedFormats()" class="px-6 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 shadow-md">
            应用选中修改
        </button>
    `;
    container.appendChild(applySection);
    lucide.createIcons();
}

function toggleAllFormatChecks(checked) {
    document.querySelectorAll('.format-check-item').forEach(cb => { cb.checked = checked; });
}

async function applySelectedFormats() {
    const checked = document.querySelectorAll('.format-check-item:checked');
    if (checked.length === 0) {
        showToast('请至少选择一项修改建议', 'error');
        return;
    }
    if (!currentProjectId) {
        showToast('请先选择项目', 'error');
        return;
    }

    const selectedSuggestions = [];
    checked.forEach(cb => {
        const idx = parseInt(cb.dataset.index);
        if (currentFormatChecklist[idx]) {
            selectedSuggestions.push(currentFormatChecklist[idx]);
        }
    });

    // Group suggestions by implied section, apply to all sections
    const sectionsResp = await api('GET', `/sections?project_id=${currentProjectId}`).catch(() => null);
    const sections = sectionsResp ? await sectionsResp.json() : [];
    if (!sections || sections.length === 0) {
        showToast('未找到可修改的章节', 'error');
        return;
    }

    showToast('正在应用格式修改...', 'info');

    let appliedCount = 0;
    for (const sec of sections) {
        try {
            const res = await (await api('POST', '/submit/format-apply', {
                project_id: currentProjectId,
                section_name: sec.section_name,
                suggestions: selectedSuggestions
            })).json();
            if (res.status === 'ok') appliedCount++;
        } catch (e) {
            console.error(`Apply failed for ${sec.section_name}:`, e);
        }
    }

    if (appliedCount > 0) {
        showToast(`已对 ${appliedCount} 个章节应用格式修改`, 'success');
    } else {
        showToast('格式修改未成功应用', 'error');
    }
}

// ---- Session Management (Multi-turn Conversation) ----
function startNewSession() {
    currentSessionId = null;
    localStorage.removeItem('citewise_session');
    const c = document.getElementById('dynamicChatContent');
    if (c) c.innerHTML = `
        <div class="flex gap-4 mb-8">
            ${AI_AVATAR}
            <div class="max-w-[80%] bg-white border border-slate-200 p-6 rounded-3xl rounded-tl-none shadow-sm space-y-4">
                <p class="text-slate-700 leading-relaxed text-sm">
                    CiteWise V3 协同系统已就绪。新对话已创建，我将自动调度 Agent 为您服务。
                </p>
            </div>
        </div>`;
    lucide.createIcons();
    showToast('新对话已创建', 'success');
    // Close history panel if open
    const panel = document.getElementById('chatHistoryPanel');
    if (panel) panel.classList.add('hidden');
}

async function loadSessionHistory() {
    if (!currentSessionId || !currentProjectId) return;
    const c = document.getElementById('dynamicChatContent');
    if (!c) return;
    // Guard: skip reload if chat already has content (preserves messages on view switch)
    if (c.querySelector('.flex.gap-4')) return;
    try {
        const messages = await (await api('GET', `/sessions/${currentSessionId}/messages`)).json();
        if (!messages || messages.length === 0) return;
        // Clear welcome message
        c.innerHTML = '';
        for (const msg of messages) {
            if (msg.role === 'user') {
                appendUserMessage(msg.content);
            } else if (msg.role === 'assistant') {
                const meta = msg.metadata || {};
                const collabId = 'collab-hist-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
                const timeline = meta.agent_timeline || [];
                const verification = meta.verification || null;
                const msgSources = meta.sources || [];
                const hasRichData = timeline.length > 0 || verification;

                const d = document.createElement('div');
                d.className = 'flex gap-4 mb-8 animate__animated animate__fadeInUp';

                if (hasRichData) {
                    // Reconstruct rich layout: timeline card + response + verification
                    const colors = {
                        Supervisor: 'border-indigo-500', Researcher: 'border-blue-500',
                        Responder: 'border-violet-500', Writer: 'border-amber-500', Analyst: 'border-emerald-500',
                    };
                    let timelineHtml = '';
                    for (const step of timeline) {
                        const borderColor = (colors[step.agent] || 'border-slate-400').replace('border-', '');
                        const statusCls = step.status === 'done' ? 'collab-step completed' : 'collab-step';
                        const durText = step.duration_ms ? ` (${step.duration_ms}ms)` : '';
                        timelineHtml += `<div class="${statusCls}" style="border-left-color:${borderColor}">${step.agent}: ${step.detail || '完成'}${durText}</div>`;
                    }

                    let coveHtml = '';
                    if (verification) {
                        const coveError = verification.error;
                        const score = verification.overall_score || 0;
                        const claimCount = verification.claim_count || 0;
                        const flaggedCount = verification.flagged_count || 0;
                        if (coveError) {
                            coveHtml = `<div class="cove-card">
                                <div class="flex items-center gap-3 mb-2">
                                    <span class="cove-score low"><i data-lucide="alert-triangle" class="w-4 h-4 inline"></i></span>
                                    <div>
                                        <div class="font-bold text-slate-700">事实性验证</div>
                                        <div class="text-amber-600 text-xs">${claimCount > 0 ? `已提取 ${claimCount} 个声明，但` : ''}${escapeHtml(coveError)}</div>
                                        <div class="text-slate-400 text-[10px] mt-1">建议稍后重新提问以触发验证</div>
                                    </div>
                                </div></div>`;
                        } else {
                            const scoreClass = score > 0.8 ? 'high' : (score > 0.5 ? 'medium' : 'low');
                            let flaggedHtml = '';
                            if (verification.flagged_claims && verification.flagged_claims.length > 0) {
                                flaggedHtml = verification.flagged_claims.map(f =>
                                    `<div class="cove-flagged-item"><strong>${escapeHtml(f.status)}</strong>: ${escapeHtml(f.claim)}${f.issue ? '<br><span class="text-slate-500">' + escapeHtml(f.issue) + '</span>' : ''}</div>`
                                ).join('');
                            }
                            coveHtml = `<div class="cove-card">
                                <div class="flex items-center gap-3 mb-2">
                                    <span class="cove-score ${scoreClass}">${(score * 100).toFixed(0)}%</span>
                                    <div>
                                        <div class="font-bold text-slate-700">事实性验证</div>
                                        <div class="text-slate-400">${claimCount} 个声明${flaggedCount > 0 ? '，<span class="text-red-500">' + flaggedCount + ' 个存疑</span>' : '，全部可信'}</div>
                                    </div>
                                </div>
                                ${flaggedHtml ? '<details><summary class="cursor-pointer text-xs text-slate-500 font-bold">查看详情</summary>' + flaggedHtml + '</details>' : ''}</div>`;
                        }
                    }

                    d.innerHTML = `
                        ${AI_AVATAR}
                        <div class="flex-1 space-y-4">
                            <div class="bg-indigo-50 border border-indigo-100 p-6 rounded-3xl rounded-tl-none">
                                <div class="flex items-center gap-2 mb-4">
                                    <span class="text-[10px] font-bold text-indigo-600 uppercase tracking-widest">Multi-Agent 协作记录</span>
                                </div>
                                <div class="space-y-1 text-xs text-indigo-900/70">${timelineHtml}</div>
                            </div>
                            <div id="${collabId}-res" class="bg-white border border-slate-200 p-6 rounded-3xl text-sm leading-relaxed shadow-sm"></div>
                            ${coveHtml}
                        </div>`;
                    c.appendChild(d);

                    // Render source-annotated text
                    const resBox = document.getElementById(collabId + '-res');
                    if (resBox && msg.content) {
                        renderCategorizedText(resBox, msg.content);
                    }
                } else {
                    // Simple fallback for messages without rich metadata
                    d.innerHTML = `
                        ${AI_AVATAR}
                        <div class="flex-1 bg-white border border-slate-200 p-6 rounded-3xl text-sm leading-relaxed shadow-sm"></div>`;
                    c.appendChild(d);
                    const resBox = d.querySelector('.bg-white.border-slate-200');
                    if (resBox && msg.content) {
                        renderCategorizedText(resBox, msg.content);
                    }
                }
            }
        }
        lucide.createIcons();
        scrollChat();
    } catch (e) {
        console.warn('Load session history failed:', e);
    }
}

// ---- Chat History Panel ----
let _chatHistorySessions = [];

function toggleChatHistory(e) {
    if (e) e.stopPropagation();
    const panel = document.getElementById('chatHistoryPanel');
    if (!panel) return;
    const wasHidden = panel.classList.contains('hidden');
    if (wasHidden) {
        // Position panel below the history button
        const btn = document.getElementById('chatHistoryBtn');
        if (btn) {
            const rect = btn.getBoundingClientRect();
            panel.style.top = (rect.bottom + 8) + 'px';
            panel.style.right = (window.innerWidth - rect.right) + 'px';
        }
    }
    panel.classList.toggle('hidden');
    if (wasHidden) loadChatHistory();
}

async function loadChatHistory() {
    if (!currentProjectId) return;
    const listEl = document.getElementById('chatHistoryList');
    const countEl = document.getElementById('chatHistoryCount');
    if (!listEl) return;
    listEl.innerHTML = '<div class="text-center text-slate-400 py-4 text-xs">加载中...</div>';
    try {
        const sessions = await (await api('GET', `/sessions?project_id=${currentProjectId}`)).json();
        _chatHistorySessions = sessions || [];
        if (countEl) countEl.textContent = `${sessions.length} 个会话`;
        if (!sessions || sessions.length === 0) {
            listEl.innerHTML = '<div class="text-center text-slate-400 py-4 text-xs">暂无历史对话</div>';
            return;
        }
        renderChatHistoryList(sessions);
    } catch (e) {
        listEl.innerHTML = '<div class="text-center text-red-400 py-4 text-xs">加载失败</div>';
        console.error('Load chat history failed:', e);
    }
}

function renderChatHistoryList(sessions) {
    const listEl = document.getElementById('chatHistoryList');
    if (!listEl) return;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 86400000);
    const weekAgo = new Date(today.getTime() - 6 * 86400000);

    const groups = { today: [], yesterday: [], week: [], older: [] };
    for (const s of sessions) {
        const d = s.created_at ? new Date(s.created_at + 'Z') : now;
        if (d >= today) groups.today.push(s);
        else if (d >= yesterday) groups.yesterday.push(s);
        else if (d >= weekAgo) groups.week.push(s);
        else groups.older.push(s);
    }

    const labels = { today: '今天', yesterday: '昨天', week: '近 7 天', older: '更早' };
    let html = '';
    for (const [key, items] of Object.entries(groups)) {
        if (items.length === 0) continue;
        html += `<div class="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-1 pt-2 pb-1">${labels[key]}</div>`;
        html += items.map(s => _renderSessionItem(s)).join('');
    }
    listEl.innerHTML = html || '<div class="text-center text-slate-400 py-4 text-xs">无匹配结果</div>';
    lucide.createIcons();
}

function _renderSessionItem(s) {
    const isActive = s.id === currentSessionId;
    const title = s.title || '未命名对话';
    const time = s.created_at ? new Date(s.created_at + (s.created_at.includes('Z') ? '' : 'Z')).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
    return `<div class="group flex items-center gap-2 p-2.5 rounded-lg cursor-pointer transition-all ${isActive ? 'bg-indigo-50 border border-indigo-200' : 'hover:bg-slate-50'}" data-action="loadSession" data-session-id="${escapeAttr(s.id)}">
        <i data-lucide="message-square" class="w-3.5 h-3.5 shrink-0 ${isActive ? 'text-indigo-500' : 'text-slate-400'}"></i>
        <div class="flex-1 min-w-0">
            <div class="text-xs font-semibold ${isActive ? 'text-indigo-700' : 'text-slate-700'} truncate" data-action="renameSession" data-session-id="${escapeAttr(s.id)}">${escapeHtml(title)}</div>
            <div class="text-[10px] text-slate-400">${time}</div>
        </div>
        <button class="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-50 hover:text-red-500 text-slate-300 transition-all shrink-0" data-action="deleteSession" data-session-id="${escapeAttr(s.id)}" title="删除">
            <i data-lucide="trash-2" class="w-3 h-3"></i>
        </button>
    </div>`;
}

function filterChatHistory(query) {
    const q = query.trim().toLowerCase();
    if (!q) {
        renderChatHistoryList(_chatHistorySessions);
        return;
    }
    const filtered = _chatHistorySessions.filter(s =>
        (s.title || '未命名对话').toLowerCase().includes(q)
    );
    renderChatHistoryList(filtered);
}

// Event delegation for chat history actions
document.addEventListener('click', (e) => {
    // Delete session
    const delBtn = e.target.closest('[data-action="deleteSession"]');
    if (delBtn) {
        e.stopPropagation();
        const sid = delBtn.dataset.sessionId;
        if (sid && confirm('确定删除该对话？')) {
            api('DELETE', `/sessions/${sid}`).then(() => {
                if (currentSessionId === sid) {
                    currentSessionId = null;
                    localStorage.removeItem('citewise_session');
                    startNewSession();
                }
                loadChatHistory();
                showToast('对话已删除', 'success');
            }).catch(e => showToast('删除失败: ' + e.message, 'error'));
        }
        return;
    }
    // Load session
    const loadBtn = e.target.closest('[data-action="loadSession"]');
    if (loadBtn) {
        e.stopPropagation();
        const sid = loadBtn.dataset.sessionId;
        if (sid) switchToSession(sid);
        return;
    }
});

// Double-click to rename session
document.addEventListener('dblclick', (e) => {
    const renameEl = e.target.closest('[data-action="renameSession"]');
    if (!renameEl) return;
    e.stopPropagation();
    const sid = renameEl.dataset.sessionId;
    if (!sid) return;
    const oldTitle = renameEl.textContent.trim();
    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldTitle;
    input.className = 'w-full text-xs font-semibold text-slate-700 bg-indigo-50 border border-indigo-300 rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-indigo-500';
    renameEl.replaceWith(input);
    input.focus();
    input.select();

    const save = async () => {
        const newTitle = input.value.trim() || oldTitle;
        if (newTitle !== oldTitle) {
            try {
                await api('PATCH', `/sessions/${sid}`, { title: newTitle });
                showToast('已重命名', 'success');
            } catch (err) {
                showToast('重命名失败', 'error');
            }
        }
        loadChatHistory();
    };
    input.addEventListener('blur', save);
    input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') input.blur();
        if (ev.key === 'Escape') { input.value = oldTitle; input.blur(); }
    });
});

async function switchToSession(sessionId) {
    currentSessionId = sessionId;
    localStorage.setItem('citewise_session', JSON.stringify(currentSessionId));
    // Close panel
    const panel = document.getElementById('chatHistoryPanel');
    if (panel) panel.classList.add('hidden');
    // Load messages
    const c = document.getElementById('dynamicChatContent');
    if (c) c.innerHTML = '';
    await loadSessionHistory();
    // Update active state in history list
    document.querySelectorAll('[data-action="loadSession"]').forEach(el => {
        const isActive = el.dataset.sessionId === sessionId;
        el.className = `group flex items-center gap-2 p-2.5 rounded-lg cursor-pointer transition-all ${isActive ? 'bg-indigo-50 border border-indigo-200' : 'hover:bg-slate-50'}`;
    });
}

// Close history panel on click outside
window.addEventListener('click', (e) => {
    const panel = document.getElementById('chatHistoryPanel');
    if (panel && !panel.classList.contains('hidden') && !e.target.closest('#chatHistoryPanel') && !e.target.closest('[onclick*="toggleChatHistory"]')) {
        panel.classList.add('hidden');
    }
});

// ============ Extraction ============
function renderFields() {
    const c = document.getElementById('fieldContainer');
    if (!c) return;
    c.innerHTML = extractionFields.map((f, i) =>
        `<div class="dimension-card relative group bg-white border border-slate-200 rounded-2xl p-4 shadow-sm text-center animate__animated animate__fadeIn">
            <div class="text-[9px] font-extrabold text-slate-300 uppercase tracking-tighter mb-1">Dimension</div>
            <div class="text-sm font-bold text-slate-700">${escapeHtml(f)}</div>
            <button onclick="extractionFields.splice(${i},1);renderFields();event.stopPropagation();" class="absolute -top-2 -right-2 w-6 h-6 bg-white border border-slate-100 rounded-full flex items-center justify-center text-slate-400 hover:text-red-500 shadow-sm opacity-0 group-hover:opacity-100 transition-opacity">
                <i data-lucide="x" class="w-3 h-3"></i>
            </button>
        </div>`
    ).join('');
    lucide.createIcons();
}

function addField() {
    const v = document.getElementById('newFieldInput').value.trim();
    if (v && !extractionFields.includes(v)) {
        extractionFields.push(v);
        document.getElementById('newFieldInput').value = '';
        renderFields();
    }
}

function removeField(i) {
    extractionFields.splice(i, 1);
    renderFields();
}

async function runExtraction() {
    if (!currentProjectId || extractionFields.length === 0) {
        showToast('请先选择项目并设置字段', 'error');
        return;
    }

    document.getElementById('extractionConfigView').classList.add('hidden');
    document.getElementById('extractionResultView').classList.remove('hidden');
    document.getElementById('extractionLoader').classList.remove('hidden');
    document.getElementById('extractionResultContent').classList.add('hidden');

    try {
        const results = await (await api('POST', '/extraction', {
            project_id: currentProjectId,
            fields: extractionFields,
        })).json();

        document.getElementById('extractionLoader').classList.add('hidden');
        document.getElementById('extractionResultContent').classList.remove('hidden');

        // Build table
        const head = document.getElementById('extractionTableHead');
        const body = document.getElementById('extractionTableBody');

        head.innerHTML = `<tr class="border-b bg-slate-50/50"><th class="p-6 font-bold">文献标题</th>${extractionFields.map(f => `<th class="p-6 font-bold">${escapeHtml(f)}</th>`).join('')}</tr>`;
        body.innerHTML = results.map(r =>
            `<tr class="border-b"><td class="p-6 font-bold">${escapeHtml(r.paper_title || '')}</td>${extractionFields.map(f => `<td class="p-6 text-slate-500 italic">${escapeHtml(r[f] || '—')}</td>`).join('')}</tr>`
        ).join('');

    } catch (e) {
        document.getElementById('extractionLoader').classList.add('hidden');
        showToast('提取失败: ' + e.message, 'error');
    }
    lucide.createIcons();
}

function exportExtraction() {
    // Simple CSV export
    const table = document.querySelector('.academic-table');
    if (!table) return;
    let csv = '';
    for (const row of table.querySelectorAll('tr')) {
        const cells = [];
        for (const cell of row.querySelectorAll('th, td')) {
            cells.push('"' + cell.textContent.trim().replace(/"/g, '""') + '"');
        }
        csv += cells.join(',') + '\n';
    }
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'extraction_results.csv';
    a.click();
    URL.revokeObjectURL(url);
}

// ============ AgentEval Dashboard ============
async function loadEvalDashboard() {
    const days = parseInt(document.getElementById('evalDaysSelect').value) || 7;
    try {
        const [metrics, trends] = await Promise.all([
            (await api('GET', `/eval/metrics?days=${days}&project_id=${currentProjectId || ''}`)).json(),
            (await api('GET', `/eval/trends?days=${days}&project_id=${currentProjectId || ''}`)).json(),
        ]);

        // Fill metric cards
        document.getElementById('metricSuccessRate').textContent = metrics.success_rate + '%';
        document.getElementById('metricSuccessCount').textContent = metrics.success_count;
        document.getElementById('metricTotal').textContent = metrics.total_tasks;
        document.getElementById('metricAccuracy').textContent = metrics.avg_accuracy || 0;
        document.getElementById('metricHallucRate').textContent = metrics.hallucination_rate + '%';
        document.getElementById('metricHallucCount').textContent = metrics.hallucination_count;
        document.getElementById('metricResponseTime').textContent = Math.round(metrics.avg_response_time_ms);
        document.getElementById('metricCost').textContent = metrics.avg_cost;
        document.getElementById('metricTotalCost').textContent = metrics.total_cost;

        // Color code based on thresholds
        colorMetricCard('metricSuccessRate', metrics.success_rate, 85, true);
        colorMetricCard('metricHallucRate', metrics.hallucination_rate, 10, false);

        // Render trend chart (CSS bars)
        renderTrendChart(trends);

        // Render suggestions
        const sugBox = document.getElementById('evalSuggestions');
        if (metrics.suggestions && metrics.suggestions.length > 0) {
            sugBox.innerHTML = metrics.suggestions.map(s =>
                `<div class="p-3 rounded-xl text-xs font-semibold leading-relaxed ${s.includes('✅') ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : 'bg-amber-50 text-amber-700 border border-amber-100'}">${escapeHtml(s)}</div>`
            ).join('');
        } else {
            sugBox.innerHTML = '<div class="text-slate-400 text-center py-8">暂无建议</div>';
        }

    } catch (e) {
        console.error('Eval load failed:', e);
        showToast('评估数据加载失败: ' + e.message, 'error');
    }
    lucide.createIcons();
}

function colorMetricCard(elId, value, threshold, higherIsBetter) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (value === 0 && elId.includes('Halluc')) return; // 0 hallucination is good
    const good = higherIsBetter ? value >= threshold : value <= threshold;
    el.classList.remove('text-red-600', 'text-emerald-600');
    el.classList.add(good ? 'text-emerald-600' : 'text-red-600');
}

function renderTrendChart(trends) {
    const box = document.getElementById('evalTrendChart');
    if (!trends || trends.length === 0) {
        box.innerHTML = '<div class="flex-1 flex items-center justify-center text-slate-400 text-sm">暂无趋势数据，发送消息后自动采集</div>';
        document.getElementById('trendDateStart').textContent = '-';
        document.getElementById('trendDateEnd').textContent = '-';
        return;
    }
    const maxTotal = Math.max(...trends.map(t => t.total), 1);
    box.innerHTML = trends.map(t => {
        const h = Math.max(4, (t.total / maxTotal) * 100);
        const successPct = t.total > 0 ? Math.round((t.successes / t.total) * 100) : 0;
        return `<div class="flex-1 flex flex-col items-center gap-1 group relative">
            <div class="w-full rounded-t-md bg-blue-500 transition-all hover:bg-blue-600 cursor-default" style="height:${h}%" title="${escapeAttr(t.date)}: ${escapeAttr(String(t.total))}次 / ${successPct}%成功"></div>
            <span class="text-[9px] text-slate-400 font-medium">${t.date.slice(5)}</span>
        </div>`;
    }).join('');
    document.getElementById('trendDateStart').textContent = trends[0].date;
    document.getElementById('trendDateEnd').textContent = trends[trends.length - 1].date;
}

// ============ Agent Status (Left Sidebar) ============
function renderAgentStatus() {
    const c = document.getElementById('agentStatusList');
    if (!c) return;
    c.innerHTML = agents.map(a => {
        const statusColor = a.status === 'RUNNING' ? 'text-amber-500' : 'text-green-500';
        return `<div onclick="switchView('agentHubView', document.getElementById('navAgentHub')); setTimeout(() => openAgentDetail('${a.id}'), 100)" class="agent-item flex items-center justify-between p-2 px-3 bg-slate-50/50 rounded-lg border border-slate-100 mb-2 text-[11px] cursor-pointer hover:bg-indigo-50 hover:border-indigo-100 transition-all">
            <span class="flex items-center gap-2">
                <i data-lucide="${a.icon}" class="w-3 h-3 text-${a.color}-500"></i>
                ${escapeHtml(a.name)}
            </span>
            <span class="font-bold ${statusColor} uppercase text-[9px]">${a.status}</span>
        </div>`;
    }).join('');
    lucide.createIcons();
}

function confirmCreateAgent() {
    const name = document.getElementById('agentNameIn').value.trim();
    if (!name) return;
    const icon = document.getElementById('agentIconIn').value.trim() || 'cpu';
    const role = document.getElementById('agentRoleIn') ? document.getElementById('agentRoleIn').value.trim() : '';
    agents.push({
        id: Date.now().toString(),
        name: name,
        icon: icon,
        status: 'READY',
        color: 'indigo',
        prompt: role || `你是${name}，一个专业的 AI 助手。`,
        description: role || '自定义 Agent',
    });
    renderAgentStatus();
    renderAgentCards();
    saveAgentConfig();
    toggleModal('createAgentModal');
    showToast('Agent 节点就绪', 'success');
}

// ============ Agent Config Center ============
function renderAgentCards() {
    const c = document.getElementById('agentListContainer');
    if (!c) return;
    if (agents.length === 0) {
        c.innerHTML = '<div class="col-span-3 text-center text-slate-400 py-12">暂无 Agent，点击右上角新建</div>';
        return;
    }
    c.innerHTML = agents.map(a => {
        const assignedSkills = skills.filter(s => s.agent === a.id);
        const assignedTools = tools.filter(t => t.agent === a.id);
        return `<div onclick="openAgentDetail('${a.id}')" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm cursor-pointer hover:border-indigo-200 transition-all">
            <div class="flex justify-between items-start mb-4">
                <div class="p-3 bg-${a.color}-50 text-${a.color}-600 rounded-xl">
                    <i data-lucide="${a.icon}" class="w-6 h-6"></i>
                </div>
                <span class="text-[8px] font-bold uppercase px-2 py-1 rounded ${a.status === 'RUNNING' ? 'bg-amber-50 text-amber-600' : 'bg-green-50 text-green-600'}">${a.status}</span>
            </div>
            <h4 class="font-bold text-slate-800 text-base mb-1">${escapeHtml(a.name)}</h4>
            <p class="text-xs text-slate-500 mb-3">${escapeHtml(a.description || '自定义 Agent')}</p>
            <div class="flex items-center gap-3 text-[10px] text-slate-400">
                <span class="flex items-center gap-1"><i data-lucide="zap" class="w-3 h-3"></i>${assignedSkills.length} Skill</span>
                <span class="flex items-center gap-1"><i data-lucide="wrench" class="w-3 h-3"></i>${assignedTools.length} Tool</span>
            </div>
        </div>`;
    }).join('');
    lucide.createIcons();
}

function openAgentDetail(agentId) {
    const a = agents.find(x => x.id === agentId);
    if (!a) return;

    // Detect context: if agentHubView is active, use hub detail panel
    const hubView = document.getElementById('agentHubView');
    const inHub = hubView && !hubView.classList.contains('hidden') && hubView.classList.contains('active');
    if (inHub) {
        // Hide config/eval tabs, show hub detail panel
        safeClassAction('agentConfigTab', 'add', 'hidden');
        safeClassAction('agentEvalTab', 'add', 'hidden');
        safeClassAction('hubAgentDetail', 'remove', 'hidden');
    } else {
        // Legacy path: toggle within agentView
        safeClassAction('agentListView', 'add', 'hidden');
        safeClassAction('agentDetailView', 'remove', 'hidden');
    }

    const assignedSkills = skills.filter(s => s.agent === agentId);
    const availableSkills = skills.filter(s => s.agent !== agentId);
    const assignedTools = tools.filter(t => t.agent === agentId);
    const availableTools = tools.filter(t => t.agent !== agentId);

    const el = inHub ? document.getElementById('hubAgentDetailContent') : document.getElementById('agentDetailContent');
    if (!el) return;

    el.innerHTML = `
        <div class="max-w-4xl mx-auto space-y-8">
            <button onclick="closeAgentDetail()" class="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 mb-2"><i data-lucide="arrow-left" class="w-4 h-4"></i> 返回列表</button>
            <div class="p-8 bg-${a.color}-50 rounded-3xl flex items-center gap-6">
                <div class="p-4 bg-${a.color}-100 rounded-2xl"><i data-lucide="${a.icon}" class="w-10 h-10 text-${a.color}-600"></i></div>
                <div class="flex-1">
                    <h2 class="text-2xl font-bold text-slate-800">${escapeHtml(a.name)}</h2>
                    <p class="text-sm text-slate-500 mt-1">${escapeHtml(a.description || '自定义 Agent')}</p>
                    <div class="flex items-center gap-3 mt-2">
                        <span class="text-[10px] font-bold uppercase px-2.5 py-1 rounded-full ${a.status === 'RUNNING' ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'}">${a.status}</span>
                        <span class="text-[10px] text-slate-400">${assignedSkills.length} Skill · ${assignedTools.length} Tool</span>
                    </div>
                </div>
                <button onclick="deleteAgent('${a.id}')" class="p-3 hover:bg-red-100 rounded-xl text-slate-400 hover:text-red-500 transition-all" title="删除 Agent"><i data-lucide="trash-2" class="w-5 h-5"></i></button>
            </div>

            <div class="bg-white border border-slate-200 rounded-2xl p-6 space-y-3">
                <div class="flex justify-between items-center">
                    <h3 class="font-bold text-slate-700">系统提示词 (System Prompt)</h3>
                    <span class="text-[10px] text-slate-400">定义 Agent 的角色和行为</span>
                </div>
                <textarea id="agentPromptEditor" class="w-full h-40 bg-slate-50 border border-slate-200 p-4 rounded-xl font-mono text-sm resize-y outline-none focus:ring-2 focus:ring-indigo-500" placeholder="输入该 Agent 的系统提示词...">${escapeHtml(a.prompt || '')}</textarea>
                <button onclick="saveAgentPrompt('${a.id}')" class="px-6 py-3 bg-indigo-600 text-white rounded-xl font-bold text-sm hover:bg-indigo-700 transition-all">保存提示词</button>
            </div>

            <div class="bg-white border border-slate-200 rounded-2xl p-6 space-y-4">
                <div class="flex justify-between items-center">
                    <h3 class="font-bold text-slate-700">已分配的 Skills</h3>
                    <span class="text-[10px] text-slate-400">${assignedSkills.length} 个</span>
                </div>
                ${assignedSkills.length > 0 ? assignedSkills.map(s => `
                    <div class="flex items-center justify-between p-4 bg-amber-50 border border-amber-100 rounded-xl">
                        <div class="flex items-center gap-3">
                            <div class="p-2 bg-amber-100 rounded-lg"><i data-lucide="${s.icon}" class="w-4 h-4 text-amber-600"></i></div>
                            <div>
                                <p class="font-bold text-sm text-slate-800">${escapeHtml(s.title)}</p>
                                <p class="text-[10px] text-slate-400">${escapeHtml(s.desc)}</p>
                            </div>
                        </div>
                        <button onclick="unassignSkill(${s.id}, '${a.id}')" class="text-[10px] px-3 py-1.5 rounded-lg bg-white border border-red-200 text-red-500 hover:bg-red-50 font-bold">移除</button>
                    </div>
                `).join('') : '<div class="text-center text-slate-400 py-6 text-xs">暂无分配的 Skill</div>'}
            </div>

            ${availableSkills.length > 0 ? `
            <div class="bg-white border border-slate-200 rounded-2xl p-6 space-y-4">
                <h3 class="font-bold text-slate-700">可分配的 Skills</h3>
                <div class="grid grid-cols-2 gap-3">
                    ${availableSkills.map(s => `
                        <div class="flex items-center justify-between p-3 bg-slate-50 border border-slate-100 rounded-xl">
                            <div class="flex items-center gap-2">
                                <i data-lucide="${s.icon}" class="w-4 h-4 text-slate-400"></i>
                                <span class="text-sm font-semibold text-slate-700">${escapeHtml(s.title)}</span>
                            </div>
                            <button onclick="assignSkill(${s.id}, '${a.id}')" class="text-[10px] px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 font-bold">分配</button>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}

            <div class="bg-white border border-slate-200 rounded-2xl p-6 space-y-4">
                <div class="flex justify-between items-center">
                    <h3 class="font-bold text-slate-700">可使用的 Tools</h3>
                    <span class="text-[10px] text-slate-400">${assignedTools.length} 个</span>
                </div>
                ${assignedTools.length > 0 ? assignedTools.map(t => `
                    <div class="flex items-center justify-between p-4 bg-blue-50 border border-blue-100 rounded-xl">
                        <div class="flex items-center gap-3">
                            <div class="p-2 bg-blue-100 rounded-lg"><i data-lucide="${t.icon}" class="w-4 h-4 text-blue-600"></i></div>
                            <div>
                                <p class="font-bold text-sm text-slate-800">${escapeHtml(t.title)}</p>
                                <p class="text-[10px] text-slate-400">${escapeHtml(t.desc)}</p>
                                <p class="text-[9px] text-slate-300 mt-0.5">指令词: ${escapeHtml(t.trigger)}</p>
                            </div>
                        </div>
                        <button onclick="unassignTool(${t.id}, '${a.id}')" class="text-[10px] px-3 py-1.5 rounded-lg bg-white border border-red-200 text-red-500 hover:bg-red-50 font-bold">移除</button>
                    </div>
                `).join('') : '<div class="text-center text-slate-400 py-6 text-xs">暂无分配的 Tool</div>'}
            </div>

            ${availableTools.length > 0 ? `
            <div class="bg-white border border-slate-200 rounded-2xl p-6 space-y-4">
                <h3 class="font-bold text-slate-700">可分配的 Tools</h3>
                <div class="grid grid-cols-2 gap-3">
                    ${availableTools.map(t => `
                        <div class="flex items-center justify-between p-3 bg-slate-50 border border-slate-100 rounded-xl">
                            <div class="flex items-center gap-2">
                                <i data-lucide="${t.icon}" class="w-4 h-4 text-slate-400"></i>
                                <span class="text-sm font-semibold text-slate-700">${escapeHtml(t.title)}</span>
                            </div>
                            <button onclick="assignTool(${t.id}, '${a.id}')" class="text-[10px] px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 font-bold">分配</button>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        </div>
    `;
    lucide.createIcons();
}

function closeAgentDetail() {
    // Check if we're in hub context
    const hubView = document.getElementById('agentHubView');
    const inHub = hubView && !hubView.classList.contains('hidden') && hubView.classList.contains('active');
    if (inHub) {
        safeClassAction('hubAgentDetail', 'add', 'hidden');
        safeClassAction('agentConfigTab', 'remove', 'hidden');
    } else {
        safeClassAction('agentListView', 'remove', 'hidden');
        safeClassAction('agentDetailView', 'add', 'hidden');
    }
}

function saveAgentPrompt(agentId) {
    const a = agents.find(x => x.id === agentId);
    const editor = document.getElementById('agentPromptEditor');
    if (a && editor) {
        a.prompt = editor.value;
        saveAgentConfig();
        showToast('提示词已保存', 'success');
    }
}

function assignSkill(skillId, agentId) {
    const s = skills.find(x => x.id === skillId);
    if (s) {
        s.agent = agentId;
        saveAgentConfig();
        openAgentDetail(agentId);
        renderSkillLibrary();
        renderAgentCards();
        showToast(`已将「${s.title}」分配给 ${agents.find(a => a.id === agentId)?.name}`, 'success');
    }
}

function unassignSkill(skillId, agentId) {
    const s = skills.find(x => x.id === skillId);
    if (s) {
        s.agent = '';
        saveAgentConfig();
        openAgentDetail(agentId);
        renderSkillLibrary();
        renderAgentCards();
        showToast(`已移除「${s.title}」`, 'success');
    }
}

function assignTool(toolId, agentId) {
    const t = tools.find(x => x.id === toolId);
    if (t) {
        t.agent = agentId;
        saveAgentConfig();
        openAgentDetail(agentId);
        renderToolLibrary();
        renderAgentCards();
        showToast(`已将「${t.title}」分配给 ${agents.find(a => a.id === agentId)?.name}`, 'success');
    }
}

function unassignTool(toolId, agentId) {
    const t = tools.find(x => x.id === toolId);
    if (t) {
        t.agent = '';
        saveAgentConfig();
        openAgentDetail(agentId);
        renderToolLibrary();
        renderAgentCards();
        showToast(`已移除「${t.title}」`, 'success');
    }
}

// ============ Agent Config Persistence ============
function saveAgentConfig() {
    localStorage.setItem('citewise_agents', JSON.stringify(agents));
    localStorage.setItem('citewise_skills', JSON.stringify(skills));
    localStorage.setItem('citewise_tools', JSON.stringify(tools));
}

function loadAgentConfig() {
    const savedAgents = localStorage.getItem('citewise_agents');
    const savedSkills = localStorage.getItem('citewise_skills');
    const savedTools = localStorage.getItem('citewise_tools');
    if (savedAgents) { try { agents = JSON.parse(savedAgents); } catch { /* keep defaults */ } }
    if (savedSkills) { try { skills = JSON.parse(savedSkills); } catch { /* keep defaults */ } }
    if (savedTools) { try { tools = JSON.parse(savedTools); } catch { /* keep defaults */ } }
}

function deleteAgent(agentId) {
    if (agents.length <= 1) {
        showToast('至少保留一个 Agent', 'error');
        return;
    }
    if (!confirm(`确定删除 Agent「${agents.find(a => a.id === agentId)?.name}」？`)) return;
    agents = agents.filter(a => a.id !== agentId);
    skills.forEach(s => { if (s.agent === agentId) s.agent = ''; });
    tools.forEach(t => { if (t.agent === agentId) t.agent = ''; });
    saveAgentConfig();
    closeAgentDetail();
    renderAgentCards();
    renderAgentStatus();
    renderSkillLibrary();
    showToast('Agent 已删除', 'success');
}

// ============ Skill & Tool Library ============
function renderSkillLibrary() {
    const c = document.getElementById('skillListContainer');
    if (!c) return;
    c.innerHTML = skills.map(s => {
        const agentName = s.agent ? (agents.find(a => a.id === s.agent)?.name || s.agent) : '未分配';
        return `<div onclick="openSkillDetail(${s.id})" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm group animate__animated animate__fadeIn cursor-pointer">
            <div class="flex justify-between items-start mb-4">
                <div class="p-2 bg-amber-50 text-amber-600 rounded-lg">
                    <i data-lucide="${s.icon}" class="w-5 h-5"></i>
                </div>
                <span class="text-[7px] uppercase font-bold ${s.agent ? 'text-blue-500' : 'text-slate-300'} mt-2">On ${escapeHtml(agentName)}</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm mb-1">${escapeHtml(s.title)}</h4>
            <p class="text-[10px] text-slate-500">${escapeHtml(s.desc)}</p>
        </div>`;
    }).join('');
    lucide.createIcons();
}

function renderToolLibrary() {
    const c = document.getElementById('toolListContainer');
    if (!c) return;
    c.innerHTML = tools.map(t => {
        const agentName = t.agent ? (agents.find(a => a.id === t.agent)?.name || t.agent) : '未分配';
        return `<div onclick="openToolDetail(${t.id})" class="interactive-card bg-white p-6 rounded-3xl border border-slate-100 shadow-sm group animate__animated animate__fadeIn cursor-pointer">
            <div class="flex justify-between mb-4">
                <div class="p-2 bg-blue-50 text-blue-600 rounded-lg">
                    <i data-lucide="${t.icon}" class="w-5 h-5"></i>
                </div>
                <span class="text-[7px] uppercase font-bold ${t.agent ? 'text-blue-500' : 'text-slate-300'} mt-2">On ${escapeHtml(agentName)}</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm mb-1">${escapeHtml(t.title)}</h4>
            <p class="text-[10px] text-slate-500">${escapeHtml(t.desc)}</p>
            <div class="mt-4 pt-3 border-t border-slate-50 text-[8px] text-slate-400 font-bold uppercase">指令词: ${escapeHtml(t.trigger)}</div>
        </div>`;
    }).join('');
    lucide.createIcons();
}

function openSkillDetail(id) {
    const s = skills.find(x => x.id === id);
    if (!s) return;
    safeClassAction('skillListView', 'add', 'hidden');
    safeClassAction('skillDetailView', 'remove', 'hidden');
    const intro = document.getElementById('skillIntro');
    if (intro) intro.innerHTML = `
        <div class="p-8 bg-amber-50 rounded-3xl text-center">
            <i data-lucide="${s.icon}" class="w-10 h-10 mx-auto mb-4 text-amber-500"></i>
            <h2 class="text-2xl font-bold">${escapeHtml(s.title)}</h2>
            <p class="text-xs text-slate-400 mt-2 uppercase font-bold">Inject to ${escapeHtml(s.agent)}</p>
        </div>
        <div class="bg-white border border-slate-200 rounded-2xl p-6 space-y-4">
            <h3 class="font-bold text-slate-700">描述</h3>
            <p class="text-slate-500 text-sm">${escapeHtml(s.desc)}</p>
        </div>
        <div class="flex gap-4">
            <button onclick="showToast('处理完成')" class="flex-1 py-4 bg-amber-500 text-white rounded-2xl font-bold shadow-lg">启动</button>
            <button onclick="deleteSkill(${s.id})" class="py-4 px-6 bg-white border border-red-200 text-red-500 rounded-2xl font-bold hover:bg-red-50 transition-all">删除</button>
        </div>
    `;
    lucide.createIcons();
}

function deleteSkill(id) {
    skills = skills.filter(s => s.id !== id);
    saveAgentConfig();
    renderSkillLibrary();
    closeAssetDetail('skill');
    showToast('Skill 已删除');
}

function openToolDetail(id) {
    const t = tools.find(x => x.id === id);
    if (!t) return;
    safeClassAction('toolListView', 'add', 'hidden');
    safeClassAction('toolDetailView', 'remove', 'hidden');

    const code = t.code || `# CiteWise Tool: ${t.title}\n# Trigger: ${t.trigger}\n\n# ${t.desc}\n\ndef run(context):\n    """Execute this tool with the given context."""\n    # TODO: Implement tool logic\n    pass`;

    const action = document.getElementById('toolActionContent');
    if (action) action.innerHTML = `
        <div class="space-y-6 max-w-4xl mx-auto">
            <div class="p-6 bg-blue-50 rounded-3xl flex items-center gap-4">
                <div class="p-3 bg-blue-100 rounded-xl"><i data-lucide="${t.icon}" class="w-6 h-6 text-blue-600"></i></div>
                <div class="flex-1">
                    <h2 class="text-xl font-bold text-slate-800">${escapeHtml(t.title)}</h2>
                    <p class="text-xs text-slate-500">${escapeHtml(t.desc)}</p>
                </div>
            </div>
            <div class="bg-white border border-slate-200 rounded-2xl p-4">
                <div class="flex justify-between items-center mb-3">
                    <span class="text-xs font-bold text-slate-500 uppercase">脚本代码</span>
                    <span class="text-[10px] font-bold text-slate-400">指令词: ${escapeHtml(t.trigger)}</span>
                </div>
                <textarea id="toolCodeEditor" class="w-full h-64 bg-slate-900 text-green-400 p-4 rounded-xl font-mono text-xs resize-y outline-none" spellcheck="false">${escapeHtml(code)}</textarea>
            </div>
            <div class="flex gap-4">
                <button onclick="saveToolCode(${t.id})" class="flex-1 py-4 bg-blue-600 text-white rounded-2xl font-bold shadow-lg">保存修改</button>
                <button onclick="runToolScript(${t.id})" class="py-4 px-6 bg-emerald-600 text-white rounded-2xl font-bold shadow-lg">运行脚本</button>
                <button onclick="deleteTool(${t.id})" class="py-4 px-6 bg-white border border-red-200 text-red-500 rounded-2xl font-bold hover:bg-red-50">删除</button>
            </div>
        </div>
    `;
    lucide.createIcons();
}

function deleteTool(id) {
    tools = tools.filter(t => t.id !== id);
    saveAgentConfig();
    renderToolLibrary();
    closeAssetDetail('tool');
    showToast('工具已删除');
}

function saveToolCode(id) {
    const t = tools.find(x => x.id === id);
    const editor = document.getElementById('toolCodeEditor');
    if (t && editor) {
        t.code = editor.value;
        showToast('脚本已保存');
    }
}

function runToolScript(id) {
    const t = tools.find(x => x.id === id);
    if (t) showToast(`运行 ${t.title}...`);
}

function handleToolFileSelect(e) {
    const file = e.target.files[0];
    if (!file || !file.name.endsWith('.py')) {
        showToast('请选择 .py 文件', 'error');
        return;
    }
    const up = document.getElementById('toolImportProgress');
    if (!up) return;
    up.classList.remove('hidden');

    const reader = new FileReader();
    reader.onload = function(ev) {
        const fileContent = ev.target.result;
        let v = 0;
        const timer = setInterval(() => {
            v += 10;
            const bar = document.getElementById('toolProgressBar');
            const txt = document.getElementById('toolProgressText');
            if (bar) bar.style.width = v + '%';
            if (txt) txt.innerText = v + '%';
            if (v >= 100) {
                clearInterval(timer);
                setTimeout(() => {
                    up.classList.add('hidden');
                    tools.unshift({
                        id: Date.now(),
                        title: file.name.split('.')[0],
                        desc: '导入的 Python 工具。',
                        icon: 'binary',
                        type: '本地',
                        trigger: '运行, run',
                        code: fileContent
                    });
                    renderToolLibrary();
                    showToast('工具脚本注入成功', 'success');
                }, 500);
            }
        }, 100);
    };
    reader.readAsText(file);
}

function openAddAssetModal(type) {
    const modal = document.getElementById('addAssetModal');
    if (!modal) return;
    const titleEl = document.getElementById('assetModalTitle');
    if (titleEl) titleEl.innerText = type === 'skill' ? '下载安装 Skill' : '添加工具脚本';
    const select = document.getElementById('skillAgentIn');
    if (select) select.innerHTML = agents.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
    modal.classList.remove('hidden');
    lucide.createIcons();
}

function confirmCreateSkill() {
    const name = document.getElementById('skillNameIn').value.trim();
    const url = document.getElementById('skillUrlIn').value.trim();
    if (!name || !url) return;
    const box = document.getElementById('installProgress');
    const bar = document.getElementById('installBar');
    const percent = document.getElementById('installPercent');
    const btn = document.getElementById('skillConfirmBtn');
    if (!box || !bar || !percent || !btn) return;

    btn.disabled = true;
    box.classList.remove('hidden');
    let v = 0;
    const timer = setInterval(() => {
        v += 10;
        bar.style.width = v + '%';
        percent.innerText = v + '%';
        if (v >= 100) {
            clearInterval(timer);
            const agentSelect = document.getElementById('skillAgentIn');
            skills.push({
                id: Date.now(),
                title: name,
                agent: agentSelect ? agentSelect.value : 'research',
                tag: '已下载',
                icon: 'zap',
                desc: '部署的能力。'
            });
            renderSkillLibrary();
            setTimeout(() => {
                toggleModal('addAssetModal');
                btn.disabled = false;
                box.classList.add('hidden');
                bar.style.width = '0%';
                percent.innerText = '0%';
                showToast('安装成功', 'success');
            }, 500);
        }
    }, 80);
}

// ============ API Key Management ============
const PROVIDER_DEFAULTS = {
    zhipu:    { name: '智谱 (GLM)',       baseUrl: 'https://open.bigmodel.cn/api/paas/v4/' },
    deepseek: { name: 'DeepSeek',          baseUrl: 'https://api.deepseek.com/v1/' },
    openai:   { name: 'OpenAI',            baseUrl: 'https://api.openai.com/v1/' },
    moonshot: { name: 'Moonshot (Kimi)',    baseUrl: 'https://api.moonshot.cn/v1/' },
    qwen:     { name: '通义千问',          baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1/' },
    custom:   { name: '自定义',            baseUrl: '' },
};

// ============ Model Selector ============
function toggleModelDropdown(e) {
    if (e) e.stopPropagation();
    const list = document.getElementById('modelDropdownList');
    const btn = document.getElementById('modelDropdownBtn');
    if (!list || !btn) return;
    list.classList.toggle('show');
    btn.classList.toggle('open');
}

function selectModel(value, label) {
    const hidden = document.getElementById('modelSelect');
    const labelEl = document.getElementById('modelDropdownLabel');
    if (hidden) hidden.value = value;
    if (labelEl) labelEl.textContent = label || '默认模型';
    // Update active state
    document.querySelectorAll('.model-dropdown-list .model-option').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.value === value);
    });
    // Close dropdown
    const list = document.getElementById('modelDropdownList');
    const btn = document.getElementById('modelDropdownBtn');
    if (list) list.classList.remove('show');
    if (btn) btn.classList.remove('open');
}

function populateModelSelector(models) {
    const list = document.getElementById('modelDropdownList');
    if (!list) return;
    const currentValue = document.getElementById('modelSelect')?.value || '';
    list.innerHTML = '';

    // Default model option
    const defaultOpt = document.createElement('div');
    defaultOpt.className = 'model-option' + (!currentValue ? ' active' : '');
    defaultOpt.dataset.value = '';
    defaultOpt.textContent = '默认模型';
    defaultOpt.onclick = (e) => { e.stopPropagation(); selectModel('', '默认模型'); };
    list.appendChild(defaultOpt);

    models.forEach(m => {
        const opt = document.createElement('div');
        opt.className = 'model-option' + (currentValue === m ? ' active' : '');
        opt.dataset.value = m;
        opt.textContent = m;
        opt.onclick = (e) => { e.stopPropagation(); selectModel(m, m); };
        list.appendChild(opt);
    });

    // Update label
    if (currentValue && models.includes(currentValue)) {
        const labelEl = document.getElementById('modelDropdownLabel');
        if (labelEl) labelEl.textContent = currentValue;
    }
}

// Init model selector from saved API keys on load
function initModelSelector() {
    const keys = loadApiKeysFromStorage();
    const active = keys.find(k => k.active);
    if (active && active.models && active.models.length > 0) {
        populateModelSelector(active.models);
    } else {
        populateModelSelector([]);
    }
}

function loadApiKeysFromStorage() {
    const saved = localStorage.getItem('citewise_api_keys');
    if (saved) {
        try { return JSON.parse(saved); } catch { /* ignore */ }
    }
    return [];
}

function saveApiKeysToStorage(keys) {
    localStorage.setItem('citewise_api_keys', JSON.stringify(keys));
}

function getActiveApiKey() {
    const keys = loadApiKeysFromStorage();
    return keys.find(k => k.active) || null;
}

function renderApiKeyList() {
    const c = document.getElementById('apiKeyListContainer');
    if (!c) return;
    const keys = loadApiKeysFromStorage();
    if (keys.length === 0) {
        c.innerHTML = '<div class="col-span-2 text-center text-slate-400 py-12">暂无 API Key 配置，点击右上角「+ 新增配置」添加</div>';
        return;
    }
    c.innerHTML = keys.map((k, i) => {
        const prov = PROVIDER_DEFAULTS[k.provider] || { name: k.provider };
        return `<div class="p-5 bg-white border border-slate-200 rounded-2xl shadow-sm cursor-pointer hover:border-blue-300 transition-all ${k.active ? 'key-card-active' : ''}" onclick="editApiKey(${i})">
            <div class="flex justify-between items-start">
                <div class="font-bold text-sm text-slate-800">${escapeHtml(prov.name)}</div>
                <span class="text-[8px] font-bold uppercase px-2 py-0.5 rounded ${k.active ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'}">${k.active ? '使用中' : '未激活'}</span>
            </div>
            <div class="text-[10px] text-slate-400 font-mono mt-1">••••${escapeHtml((k.apiKey || '').slice(-4))}</div>
            <div class="text-[9px] text-slate-300 mt-1 truncate">${escapeHtml(k.baseUrl || '')}</div>
            <div class="flex gap-2 mt-3">
                <button onclick="event.stopPropagation();activateApiKey(${i})" class="text-[9px] px-2 py-1 rounded-lg ${k.active ? 'bg-emerald-50 text-emerald-600 font-bold' : 'bg-slate-50 text-slate-500 hover:bg-blue-50 hover:text-blue-600'}">${k.active ? '当前' : '启用'}</button>
                <button onclick="event.stopPropagation();confirmDeleteApiKey(${i})" class="text-[9px] px-2 py-1 rounded-lg bg-slate-50 text-slate-400 hover:bg-red-50 hover:text-red-500">删除</button>
            </div>
        </div>`;
    }).join('');
}

function onProviderChange() {
    const sel = document.getElementById('keyProviderSelect');
    const urlInput = document.getElementById('keyBaseUrlInput');
    if (!sel || !urlInput) return;
    const provider = sel.value;
    const prov = PROVIDER_DEFAULTS[provider];
    if (prov && prov.baseUrl) {
        urlInput.value = prov.baseUrl;
    }
}

function editApiKey(index) {
    const keys = loadApiKeysFromStorage();
    if (index >= 0 && index < keys.length) {
        const k = keys[index];
        document.getElementById('keyProviderSelect').value = k.provider || 'custom';
        document.getElementById('keyValueInput').value = k.apiKey || '';
        document.getElementById('keyBaseUrlInput').value = k.baseUrl || '';
        document.getElementById('keyDeleteBtn').classList.remove('hidden');
        document.getElementById('keyDeleteBtn').onclick = () => { deleteApiKeyByIndex(index); };
    }
    const resultEl = document.getElementById('keyVerifyResult');
    if (resultEl) resultEl.classList.add('hidden');
    toggleModal('keyModal');
}

function activateApiKey(index) {
    const keys = loadApiKeysFromStorage();
    keys.forEach((k, i) => { k.active = (i === index); });
    saveApiKeysToStorage(keys);
    renderApiKeyList();
    showToast(`已切换到 ${PROVIDER_DEFAULTS[keys[index].provider]?.name || keys[index].provider}`, 'success');
}

function confirmDeleteApiKey(index) {
    const keys = loadApiKeysFromStorage();
    const prov = PROVIDER_DEFAULTS[keys[index]?.provider] || { name: '' };
    if (confirm(`确定删除「${prov.name}」的 API Key 配置？`)) {
        deleteApiKeyByIndex(index);
    }
}

function deleteApiKeyByIndex(index) {
    let keys = loadApiKeysFromStorage();
    const wasActive = keys[index]?.active;
    keys.splice(index, 1);
    if (wasActive && keys.length > 0) keys[0].active = true;
    saveApiKeysToStorage(keys);
    renderApiKeyList();
    toggleModal('keyModal');
    showToast('API Key 已删除', 'success');
}

async function verifyAndSaveApiKey() {
    const provider = document.getElementById('keyProviderSelect')?.value || 'zhipu';
    const apiKey = document.getElementById('keyValueInput')?.value.trim() || '';
    const baseUrl = document.getElementById('keyBaseUrlInput')?.value.trim() || '';
    const resultEl = document.getElementById('keyVerifyResult');
    const btn = document.getElementById('keyVerifyBtn');

    if (!apiKey) {
        if (resultEl) { resultEl.textContent = '请输入 API Key'; resultEl.className = 'text-xs font-bold p-2 rounded-lg text-red-600 bg-red-50'; resultEl.classList.remove('hidden'); }
        return;
    }

    if (btn) { btn.disabled = true; btn.textContent = '验证中...'; }

    try {
        const verifyHeaders = { 'Content-Type': 'application/json' };
        if (currentUser && currentUser.token) {
            verifyHeaders['Authorization'] = `Bearer ${currentUser.token}`;
        }
        const resp = await fetch(`${API_BASE}/api/apikeys/verify`, {
            method: 'POST',
            headers: verifyHeaders,
            body: JSON.stringify({ api_key: apiKey, provider, base_url: baseUrl }),
        });
        const data = await resp.json();

        if (data.valid) {
            // Save to key list
            let keys = loadApiKeysFromStorage();
            // Check if same provider already exists -> update
            const existingIdx = keys.findIndex(k => k.provider === provider);
            const newKey = {
                provider,
                apiKey,
                baseUrl: data.base_url || baseUrl || PROVIDER_DEFAULTS[provider]?.baseUrl || '',
                models: data.models || [],
                active: true,
            };
            if (existingIdx >= 0) {
                keys[existingIdx] = newKey;
            } else {
                keys.push(newKey);
            }
            // Only one active at a time
            keys.forEach((k, i) => {
                const isNew = (existingIdx >= 0 && i === existingIdx) || (existingIdx < 0 && i === keys.length - 1);
                k.active = isNew;
            });
            saveApiKeysToStorage(keys);
            renderApiKeyList();
            populateModelSelector(data.models || []);

            // Also save to backend if logged in
            if (currentUser) {
                try {
                    const saveKeyHeaders = { 'Content-Type': 'application/json' };
                    if (currentUser && currentUser.token) {
                        saveKeyHeaders['Authorization'] = `Bearer ${currentUser.token}`;
                    }
                    await fetch(`${API_BASE}/api/apikeys/save`, {
                        method: 'POST',
                        headers: saveKeyHeaders,
                        body: JSON.stringify({ api_key: apiKey, user_id: currentUser.id }),
                    });
                } catch { /* non-critical */ }
            }

            if (resultEl) {
                resultEl.textContent = data.message;
                resultEl.className = 'text-xs font-bold p-2 rounded-lg text-emerald-600 bg-emerald-50 border border-emerald-100';
                resultEl.classList.remove('hidden');
            }
            showToast('API Key 验证成功', 'success');
            setTimeout(() => toggleModal('keyModal'), 1200);
        } else {
            if (resultEl) {
                resultEl.textContent = data.message;
                resultEl.className = 'text-xs font-bold p-2 rounded-lg text-red-600 bg-red-50 border border-red-100';
                resultEl.classList.remove('hidden');
            }
        }
    } catch (e) {
        if (resultEl) {
            resultEl.textContent = '验证请求失败: ' + e.message;
            resultEl.className = 'text-xs font-bold p-2 rounded-lg text-red-600 bg-red-50';
            resultEl.classList.remove('hidden');
        }
    }

    if (btn) { btn.disabled = false; btn.textContent = '验证'; }
}

// ============ TTS Placeholder ============

// ============ UI Helpers ============
function safeClassAction(id, action, className) {
    const el = document.getElementById(id);
    if (el) el.classList[action](className);
}

function closeAssetDetail(type) {
    safeClassAction(`${type}ListView`, 'remove', 'hidden');
    safeClassAction(`${type}DetailView`, 'add', 'hidden');
}

function switchView(id, btn) {
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(i => {
        i.classList.remove('active', 'bg-blue-50', 'text-blue-700');
    });
    const target = document.getElementById(id);
    if (target) target.classList.add('active');
    if (btn) btn.classList.add('active');

    closePaperDetail();
    closeDraftEditor();
    closeAgentDetail();
    closeAllDropdowns();

    // Show Quick Note FAB only on paperView
    const fab = document.getElementById('quickNoteFab');
    if (fab) fab.style.display = (id === 'paperView') ? '' : 'none';

    // Initialize combined views
    if (id === 'extensionView') {
        switchExtensionTab('skillTab');
    } else if (id === 'agentHubView') {
        switchAgentHubTab('agentConfigTab');
    } else if (id === 'submitView') {
        switchSubmitTab('journalTab');
    } else if (id === 'chatView') {
        // Reload chat history if chat area is empty (e.g. first switch back)
        const chatContent = document.getElementById('dynamicChatContent');
        if (chatContent && !chatContent.querySelector('.flex.gap-4')) {
            loadSessionHistory();
        }
    }
}

function toggleModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('hidden');
    if (id === 'summaryModal') renderFields();
    if (id === 'newDraftModal' && !el?.classList.contains('hidden')) populateDraftAgents();
}

function populateDraftAgents() {
    const select = document.getElementById('draftAgent');
    if (!select) return;
    const agentList = (typeof agents !== 'undefined' && agents) ? agents : [];
    select.innerHTML = agentList.map(a => {
        const role = a.prompt ? ` — ${a.prompt.slice(0, 30)}${a.prompt.length > 30 ? '...' : ''}` : '';
        return `<option value="${escapeAttr(a.id)}">${escapeHtml(a.name)}${role}</option>`;
    }).join('');
}

function toggleDropdown(id, e) {
    if (e) e.stopPropagation();
    const el = document.getElementById(id);
    if (el) el.classList.toggle('show');
}

function closeAllDropdowns() {
    document.querySelectorAll('.dropdown-menu').forEach(d => d.classList.remove('show'));
}

function scrollChat() {
    const win = document.getElementById('chatWindow');
    if (win) win.scrollTo({ top: win.scrollHeight, behavior: 'smooth' });
}

function showToast(msg, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// ============ Quick Note Functions ============
function openQuickNoteModal() {
    const modal = document.getElementById('quickNoteModal');
    const content = document.getElementById('qnContent');
    const url = document.getElementById('qnUrl');
    const linked = document.getElementById('qnLinkedPapers');
    const saveBtn = document.getElementById('qnSaveBtn');
    const suggestion = document.getElementById('qnTypeSuggestion');
    if (content) content.value = '';
    if (url) url.value = '';
    if (linked) { linked.classList.add('hidden'); linked.innerHTML = ''; }
    if (suggestion) suggestion.classList.add('hidden');
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '保存并关联文献'; saveBtn.style.display = ''; saveBtn.onclick = saveQuickNote; }
    // Re-enable fields that viewNoteLinks may have disabled
    const qnContent = document.getElementById('qnContent');
    const qnUrl = document.getElementById('qnUrl');
    const qnType = document.getElementById('qnType');
    if (qnContent) qnContent.disabled = false;
    if (qnUrl) qnUrl.disabled = false;
    if (qnType) qnType.disabled = false;
    if (modal) modal.classList.remove('hidden');
    loadNoteTypes();
    if (content) content.focus();
}

function closeQuickNoteModal() {
    const modal = document.getElementById('quickNoteModal');
    if (modal) modal.classList.add('hidden');
}

// ===== Note Types =====

let _noteTypes = [];
let _pendingSuggestion = null;

async function loadNoteTypes() {
    if (!currentProjectId) return;
    try {
        const types = await (await api('GET', `/notes/types?project_id=${currentProjectId}`)).json();
        _noteTypes = types;
        // Populate dropdown
        const select = document.getElementById('qnType');
        const filter = document.getElementById('noteTypeFilter');
        if (select) {
            select.innerHTML = types.map(t => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`).join('');
        }
        if (filter) {
            filter.innerHTML = '<option value="">全部类型</option>' + types.map(t => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`).join('');
        }
    } catch (e) {
        console.error('Load note types failed:', e);
    }
}

function openNoteTypeManager() {
    renderNoteTypeList();
    document.getElementById('noteTypeModal').classList.remove('hidden');
}

function renderNoteTypeList() {
    const list = document.getElementById('noteTypeList');
    if (!list) return;
    list.innerHTML = _noteTypes.map(t => `
        <div class="flex items-center gap-3 p-3 bg-slate-50 rounded-xl group">
            <span class="w-3 h-3 rounded-full bg-${t.color}-400 shrink-0"></span>
            <span class="flex-1 text-sm font-semibold text-slate-700">${escapeHtml(t.name)}</span>
            <button onclick="renameNoteType('${escapeJs(t.id)}', '${escapeJs(t.name)}')" class="p-1 hover:bg-white rounded text-slate-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition-opacity" title="重命名">
                <i data-lucide="pencil" class="w-3 h-3"></i>
            </button>
            <button onclick="deleteNoteType('${escapeJs(t.id)}')" class="p-1 hover:bg-white rounded text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity" title="删除">
                <i data-lucide="trash-2" class="w-3 h-3"></i>
            </button>
        </div>
    `).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function addNoteType(color) {
    if (!currentProjectId) return;
    const input = document.getElementById('newTypeName');
    const name = input ? input.value.trim() : '';
    if (!name) { showToast('请输入分类名称', 'error'); return; }
    try {
        await api('POST', '/notes/types', { project_id: currentProjectId, name, color });
        input.value = '';
        showToast('分类已添加');
        await loadNoteTypes();
        renderNoteTypeList();
    } catch (e) { showToast('添加失败', 'error'); }
}

async function renameNoteType(typeId, oldName) {
    const newName = prompt('重命名分类:', oldName);
    if (!newName || newName === oldName) return;
    try {
        await api('PUT', `/notes/types/${typeId}`, { name: newName });
        showToast('已重命名');
        await loadNoteTypes();
        renderNoteTypeList();
    } catch (e) { showToast('重命名失败', 'error'); }
}

async function deleteNoteType(typeId) {
    if (!confirm('删除此分类？关联笔记将重置为"通用笔记"')) return;
    try {
        await api('DELETE', `/notes/types/${typeId}`);
        showToast('已删除');
        await loadNoteTypes();
        renderNoteTypeList();
    } catch (e) { showToast('删除失败', 'error'); }
}

// ===== Save Note =====

async function saveQuickNote() {
    if (!currentProjectId) { showToast('请先选择项目', 'error'); return; }
    const content = document.getElementById('qnContent').value.trim();
    if (!content) { showToast('请输入笔记内容', 'error'); return; }

    const url = document.getElementById('qnUrl').value.trim();
    const noteType = document.getElementById('qnType').value;
    const saveBtn = document.getElementById('qnSaveBtn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '保存中...'; }

    try {
        const note = await (await api('POST', '/notes', {
            project_id: currentProjectId, content, source_url: url, note_type: noteType
        })).json();
        showToast('笔记已保存');
        if (note.linked_papers && note.linked_papers.length > 0) {
            renderLinkedPapers(note.linked_papers);
        }
        if (saveBtn) { saveBtn.textContent = '已保存'; }
        if (document.getElementById('notesTab') && !document.getElementById('notesTab').classList.contains('hidden')) {
            loadNotesList();
        }
        // Auto-suggest type after save
        suggestNoteType(note.id);
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '保存并关联文献'; }
    }
}

function renderLinkedPapers(papers) {
    const container = document.getElementById('qnLinkedPapers');
    if (!container || !papers.length) return;
    container.classList.remove('hidden');
    container.innerHTML = `
        <div class="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">AI 关联文献</div>
        ${papers.map(p => `
            <div class="flex items-center gap-3 p-3 bg-blue-50 border border-blue-100 rounded-xl cursor-pointer hover:bg-blue-100 transition-all" onclick="openPaperFromNote('${escapeJs(p.paper_id)}')">
                <i data-lucide="file-text" class="w-4 h-4 text-blue-500 shrink-0"></i>
                <div class="min-w-0 flex-1">
                    <p class="text-xs font-semibold text-slate-700 truncate">${escapeHtml(p.title || '未知标题')}</p>
                    <p class="text-[10px] text-slate-400">${escapeHtml(p.authors || '')}</p>
                </div>
                <span class="text-[10px] text-blue-500 font-bold shrink-0">${Math.round((1 - p.distance) * 100)}%</span>
            </div>
        `).join('')}`;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function openPaperFromNote(paperId) {
    closeQuickNoteModal();
    switchView('paperView', document.getElementById('navPaper'));
    setTimeout(() => openPaperDetail(paperId), 300);
}

function switchPaperTab(tabId) {
    const tabs = ['paperListTab', 'notesTab'];
    const btns = ['paperListTabBtn', 'notesTabBtn'];
    const uploadBtn = document.getElementById('paperUploadBtn');
    tabs.forEach((t, i) => {
        const el = document.getElementById(t);
        const btn = document.getElementById(btns[i]);
        if (el) el.classList.toggle('hidden', t !== tabId);
        if (btn) { btn.classList.toggle('active', t === tabId); }
    });
    if (uploadBtn) uploadBtn.classList.toggle('hidden', tabId !== 'paperListTab');
    if (tabId === 'notesTab') {
        loadNoteTypes();
        loadNotesList();
    }
}

// ===== Notes List =====

async function loadNotesList() {
    if (!currentProjectId) return;
    const container = document.getElementById('notesListContainer');
    const empty = document.getElementById('notesEmpty');
    const countEl = document.getElementById('noteCount');
    const filterEl = document.getElementById('noteTypeFilter');
    if (!container) return;

    const typeFilter = filterEl ? filterEl.value : '';
    const query = `project_id=${currentProjectId}&limit=50` + (typeFilter ? `&note_type=${encodeURIComponent(typeFilter)}` : '');

    try {
        const notes = await (await api('GET', `/notes?${query}`)).json();

        if (!notes.length) {
            if (empty) empty.classList.remove('hidden');
            container.innerHTML = '';
            if (countEl) countEl.textContent = '';
            return;
        }
        if (empty) empty.classList.add('hidden');
        if (countEl) countEl.textContent = `${notes.length} 条笔记`;

        // Build type color map from _noteTypes
        const typeColorMap = {};
        _noteTypes.forEach(t => { typeColorMap[t.name] = t.color; });

        container.innerHTML = notes.map(n => {
            const linkedCount = (n.linked_paper_ids || []).length;
            const typeName = n.note_type || '通用笔记';
            const typeColor = typeColorMap[typeName] || 'slate';
            const preview = n.content.length > 120 ? n.content.slice(0, 120) + '...' : n.content;
            const time = n.created_at ? n.created_at.slice(0, 16).replace('T', ' ') : '';
            const isPinned = n.pinned === 1;
            return `
            <div class="bg-white border ${isPinned ? 'border-blue-300 bg-blue-50/30' : 'border-slate-200'} rounded-2xl p-5 hover:shadow-md transition-all ${isPinned ? 'ring-1 ring-blue-200' : ''}">
                <div class="flex items-start justify-between gap-4">
                    <div class="flex-1 min-w-0">
                        ${isPinned ? '<div class="flex items-center gap-1 mb-1 text-[10px] text-blue-500 font-bold"><i data-lucide="pin" class="w-3 h-3"></i> 置顶</div>' : ''}
                        <p class="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">${escapeHtml(preview)}</p>
                        <div class="flex items-center gap-3 mt-3 text-[10px] text-slate-400">
                            <span>${time}</span>
                            <span class="px-2 py-0.5 bg-${typeColor}-50 text-${typeColor}-600 rounded-full font-bold">${escapeHtml(typeName)}</span>
                            ${linkedCount ? `<span class="flex items-center gap-1 text-blue-500"><i data-lucide="link" class="w-3 h-3"></i>${linkedCount} 篇关联</span>` : ''}
                            ${n.source_url ? `<a href="${escapeAttr(n.source_url)}" target="_blank" class="text-indigo-400 hover:underline truncate max-w-[150px]">${escapeHtml(n.source_url.replace(/^https?:\/\//, '').slice(0, 30))}</a>` : ''}
                        </div>
                    </div>
                    <div class="flex items-center gap-1 shrink-0">
                        <button onclick="togglePinNote('${escapeJs(n.id)}')" class="p-1.5 hover:bg-slate-100 rounded-lg ${isPinned ? 'text-blue-500' : 'text-slate-300 hover:text-slate-500'}" title="${isPinned ? '取消置顶' : '置顶'}">
                            <i data-lucide="pin" class="w-3.5 h-3.5"></i>
                        </button>
                        <button onclick="suggestNoteTypeForCard('${escapeJs(n.id)}')" class="p-1.5 hover:bg-amber-50 rounded-lg text-slate-300 hover:text-amber-500" title="AI 分类">
                            <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                        </button>
                        <button onclick="editNote('${escapeJs(n.id)}')" class="p-1.5 hover:bg-slate-100 rounded-lg text-slate-400 hover:text-slate-600" title="编辑">
                            <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                        </button>
                        <button onclick="deleteNote('${escapeJs(n.id)}')" class="p-1.5 hover:bg-red-50 rounded-lg text-slate-400 hover:text-red-500" title="删除">
                            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                </div>
                ${linkedCount ? `<div class="mt-3 pt-3 border-t border-slate-100 flex items-center gap-2">
                    <button onclick="viewNoteLinks('${escapeJs(n.id)}')" class="text-[10px] font-bold text-blue-500 hover:text-blue-700 flex items-center gap-1">
                        <i data-lucide="eye" class="w-3 h-3"></i> 查看关联文献
                    </button>
                    <button onclick="relinkNotePapers('${escapeJs(n.id)}')" class="text-[10px] font-bold text-slate-400 hover:text-indigo-500 flex items-center gap-1">
                        <i data-lucide="refresh-cw" class="w-3 h-3"></i> 重新关联
                    </button>
                </div>` : ''}
            </div>`;
        }).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        showToast('加载笔记失败: ' + e.message, 'error');
    }
}

async function deleteNote(noteId) {
    if (!confirm('确定删除这条笔记？')) return;
    try {
        await api('DELETE', `/notes/${noteId}`);
        showToast('已删除');
        loadNotesList();
    } catch (e) { showToast('删除失败', 'error'); }
}

async function editNote(noteId) {
    try {
        const n = await (await api('GET', `/notes/${noteId}`)).json();
        openQuickNoteModal();
        document.getElementById('qnContent').value = n.content;
        document.getElementById('qnUrl').value = n.source_url || '';
        document.getElementById('qnType').value = n.note_type || '通用笔记';
        const saveBtn = document.getElementById('qnSaveBtn');
        saveBtn.textContent = '更新笔记';
        saveBtn.onclick = async () => {
            const content = document.getElementById('qnContent').value.trim();
            if (!content) { showToast('内容不能为空', 'error'); return; }
            saveBtn.disabled = true; saveBtn.textContent = '更新中...';
            try {
                await api('PUT', `/notes/${noteId}`, {
                    content,
                    source_url: document.getElementById('qnUrl').value.trim(),
                    note_type: document.getElementById('qnType').value,
                });
                showToast('已更新'); closeQuickNoteModal(); loadNotesList();
            } catch (e) {
                showToast('更新失败', 'error');
                saveBtn.disabled = false;
                saveBtn.textContent = '更新笔记';
                // Keep the edit handler, don't reset to saveQuickNote
            }
        };
    } catch (e) { showToast('加载笔记失败', 'error'); }
}

async function viewNoteLinks(noteId) {
    try {
        const note = await (await api('GET', `/notes/${noteId}`)).json();
        if (note.linked_paper_ids && note.linked_paper_ids.length) {
            openQuickNoteModal();
            document.getElementById('qnContent').value = note.content;
            document.getElementById('qnContent').disabled = true;
            document.getElementById('qnUrl').disabled = true;
            document.getElementById('qnType').disabled = true;
            document.getElementById('qnSaveBtn').style.display = 'none';
            const papers = [];
            for (const pid of note.linked_paper_ids) {
                try {
                    const pd = await (await api('GET', `/papers/${pid}`)).json();
                    papers.push({ paper_id: pid, title: pd.title, authors: pd.authors, distance: 0 });
                } catch {}
            }
            if (papers.length) renderLinkedPapers(papers);
        }
    } catch (e) { showToast('加载失败', 'error'); }
}

async function relinkNotePapers(noteId) {
    showToast('重新关联中...');
    try {
        await api('POST', `/notes/${noteId}/link-papers`);
        showToast('关联已更新'); loadNotesList();
    } catch (e) { showToast('关联失败', 'error'); }
}

// ===== Pin & Reorder =====

async function togglePinNote(noteId) {
    try {
        const result = await (await api('POST', `/notes/${noteId}/pin`)).json();
        showToast(result.pinned ? '已置顶' : '已取消置顶');
        loadNotesList();
    } catch (e) { showToast('操作失败', 'error'); }
}

// ===== AI Classification =====

async function suggestNoteType(noteId) {
    try {
        const result = await (await api('POST', `/notes/${noteId}/suggest-type`)).json();
        if (result.suggested_type && result.confidence > 0.5) {
            _pendingSuggestion = { noteId, type: result.suggested_type };
            const banner = document.getElementById('qnTypeSuggestion');
            const text = document.getElementById('qnSuggestionText');
            if (banner && text) {
                text.textContent = `AI 建议: ${result.suggested_type} (${Math.round(result.confidence * 100)}%)`;
                banner.classList.remove('hidden');
            }
        }
    } catch (e) { /* silent */ }
}

async function suggestNoteTypeForCard(noteId) {
    showToast('AI 分析中...');
    try {
        const result = await (await api('POST', `/notes/${noteId}/suggest-type`)).json();
        if (result.suggested_type && result.confidence > 0.3) {
            // Apply directly
            await api('PUT', `/notes/${noteId}`, { note_type: result.suggested_type });
            showToast(`已分类为: ${result.suggested_type}`);
            loadNotesList();
        } else {
            showToast('AI 无法确定分类');
        }
    } catch (e) { showToast('分类失败', 'error'); }
}

function applySuggestedType() {
    if (!_pendingSuggestion) return;
    const { noteId, type } = _pendingSuggestion;
    api('PUT', `/notes/${noteId}`, { note_type: type }).then(() => {
        showToast('已应用 AI 建议');
        const select = document.getElementById('qnType');
        if (select) select.value = type;
        dismissSuggestion();
        loadNotesList();
    }).catch(() => showToast('应用失败', 'error'));
}

function dismissSuggestion() {
    _pendingSuggestion = null;
    const banner = document.getElementById('qnTypeSuggestion');
    if (banner) banner.classList.add('hidden');
}

async function batchClassifyNotes() {
    if (!currentProjectId) { showToast('请先选择项目', 'error'); return; }
    if (!confirm('AI 将自动分类所有"通用笔记"类型的笔记，确定继续？')) return;
    showToast('AI 批量分类中...');
    try {
        const result = await (await api('POST', '/notes/batch-classify', { project_id: currentProjectId })).json();
        showToast(`已完成 ${result.classified} 条分类`);
        loadNotesList();
    } catch (e) { showToast('分类失败', 'error'); }
}

// ===== Merge =====

async function showMergeSuggestions() {
    if (!currentProjectId) { showToast('请先选择项目', 'error'); return; }
    document.getElementById('mergeModal').classList.remove('hidden');
    document.getElementById('mergeLoading').classList.remove('hidden');
    document.getElementById('mergePairsList').innerHTML = '';
    document.getElementById('mergeEmpty').classList.add('hidden');
    document.getElementById('mergeAllBtn').classList.add('hidden');

    try {
        const result = await (await api('POST', '/notes/merge-suggestions', { project_id: currentProjectId })).json();
        document.getElementById('mergeLoading').classList.add('hidden');

        if (!result.pairs || !result.pairs.length) {
            document.getElementById('mergeEmpty').classList.remove('hidden');
            return;
        }

        document.getElementById('mergeAllBtn').classList.remove('hidden');
        document.getElementById('mergePairsList').innerHTML = result.pairs.map((p, i) => `
            <div class="bg-slate-50 border border-slate-200 rounded-2xl p-4" data-pair="${i}">
                <div class="flex items-center justify-between mb-3">
                    <span class="text-xs font-bold text-purple-600">相似度 ${Math.round(p.similarity * 100)}%</span>
                    <div class="flex gap-2">
                        <button onclick="acceptMerge('${escapeJs(p.note_a.id)}', '${escapeJs(p.note_b.id)}', ${i})" class="px-3 py-1 bg-purple-600 text-white rounded-lg text-[10px] font-bold hover:bg-purple-700">合并</button>
                        <button onclick="dismissMerge(${i})" class="px-3 py-1 bg-white border border-slate-200 text-slate-500 rounded-lg text-[10px] font-bold hover:bg-slate-100">忽略</button>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div class="bg-white rounded-xl p-3 border border-slate-100">
                        <span class="text-[10px] font-bold text-slate-400 mb-1 block">${escapeHtml(p.note_a.type)}</span>
                        <p class="text-xs text-slate-700 line-clamp-3">${escapeHtml(p.note_a.content)}</p>
                    </div>
                    <div class="bg-white rounded-xl p-3 border border-slate-100">
                        <span class="text-[10px] font-bold text-slate-400 mb-1 block">${escapeHtml(p.note_b.type)}</span>
                        <p class="text-xs text-slate-700 line-clamp-3">${escapeHtml(p.note_b.content)}</p>
                    </div>
                </div>
            </div>
        `).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        document.getElementById('mergeLoading').classList.add('hidden');
        showToast('分析失败', 'error');
    }
}

async function acceptMerge(keepId, absorbId, pairIndex) {
    try {
        await api('POST', '/notes/merge', { keep_id: keepId, absorb_ids: [absorbId] });
        showToast('已合并');
        dismissMerge(pairIndex);
        loadNotesList();
    } catch (e) { showToast('合并失败', 'error'); }
}

function dismissMerge(pairIndex) {
    const el = document.querySelector(`[data-pair="${pairIndex}"]`);
    if (el) el.remove();
    // Check if any pairs left
    if (!document.getElementById('mergePairsList').children.length) {
        document.getElementById('mergeEmpty').classList.remove('hidden');
        document.getElementById('mergeAllBtn').classList.add('hidden');
    }
}

async function executeAllMerges() {
    const pairs = document.querySelectorAll('[data-pair]');
    if (!pairs.length) return;
    let merged = 0;
    // Collect all pair data before DOM changes
    const pairData = Array.from(pairs).map(el => {
        const btn = el.querySelector('button');
        return btn ? btn.getAttribute('onclick') : null;
    });
    for (const onclickStr of pairData) {
        if (!onclickStr) continue;
        const match = onclickStr.match(/acceptMerge\('([^']+)','([^']+)',(\d+)\)/);
        if (!match) continue;
        try {
            await api('POST', '/notes/merge', { keep_id: match[1], absorb_ids: [match[2]] });
            merged++;
        } catch (e) { /* skip failed merges */ }
    }
    showToast(`已完成 ${merged} 对合并`);
    document.getElementById('mergeModal').classList.add('hidden');
    loadNotesList();
}

// Keyboard shortcut: Shift+N
document.addEventListener('keydown', (e) => {
    if (e.shiftKey && e.key === 'N' && !e.ctrlKey && !e.altKey && !e.metaKey) {
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable) return;
        e.preventDefault();
        openQuickNoteModal();
    }
});

// ============ End Quick Note ============

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/`/g, '&#96;');
}

/** Escape string for use inside JS single-quoted strings within HTML onclick attributes */
function escapeJs(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ============ Auth Functions ============
function showAuthModal(mode) {
    authMode = mode || 'login';
    const title = document.getElementById('authModalTitle');
    const submitBtn = document.getElementById('authSubmitBtn');
    const toggleBtn = document.getElementById('authToggleBtn');
    if (authMode === 'login') {
        if (title) title.textContent = '登录';
        if (submitBtn) submitBtn.textContent = '登录';
        if (toggleBtn) toggleBtn.textContent = '没有账号？立即注册';
    } else {
        if (title) title.textContent = '注册';
        if (submitBtn) submitBtn.textContent = '注册';
        if (toggleBtn) toggleBtn.textContent = '已有账号？立即登录';
    }
    // Clear form & errors
    const errEl = document.getElementById('authError');
    if (errEl) errEl.classList.add('hidden');
    const userIn = document.getElementById('authUsername');
    const passIn = document.getElementById('authPassword');
    if (userIn) userIn.value = '';
    if (passIn) passIn.value = '';
    // Always SHOW modal (never toggle — avoids closing when switching modes)
    const modal = document.getElementById('authModal');
    if (modal) modal.classList.remove('hidden');
}

function toggleAuthMode() {
    showAuthModal(authMode === 'login' ? 'register' : 'login');
}

function closeAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) modal.classList.add('hidden');
}

async function handleAuth() {
    const username = document.getElementById('authUsername').value.trim();
    const password = document.getElementById('authPassword').value;
    const errEl = document.getElementById('authError');
    if (!username || !password) {
        if (errEl) { errEl.textContent = '请填写用户名和密码'; errEl.classList.remove('hidden'); }
        return;
    }

    const endpoint = authMode === 'login' ? '/auth/login' : '/auth/register';
    try {
        const resp = await fetch(`${API_BASE}/api${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });

        // Parse JSON safely — server may return HTML on 500
        let data;
        try { data = await resp.json(); } catch { data = {}; }

        if (!resp.ok) {
            if (errEl) {
                let msg = data.detail || `请求失败 (${resp.status})`;
                if (Array.isArray(msg)) {
                    msg = msg.map(e => e.msg || String(e)).join('; ');
                }
                errEl.textContent = msg;
                errEl.classList.remove('hidden');
            }
            return;
        }

        currentUser = { id: data.user.id, username: data.user.username, token: data.token };
        localStorage.setItem('citewise_user', JSON.stringify(currentUser));
        updateAuthUI();
        closeAuthModal();
        showToast(authMode === 'login' ? '登录成功' : '注册成功', 'success');
        await loadProjects();
    } catch (e) {
        if (errEl) { errEl.textContent = '网络错误: ' + e.message; errEl.classList.remove('hidden'); }
    }
}

function logout() {
    currentUser = null;
    localStorage.removeItem('citewise_user');
    currentProjectId = null;
    updateAuthUI();
    const c = document.getElementById('projectListContainer');
    if (c) c.innerHTML = '<div class="text-center text-slate-400 py-8 text-xs">请登录后查看项目</div>';
    showToast('已登出', 'success');
}

function updateAuthUI() {
    const name = currentUser ? currentUser.username : '未登录';
    const initial = currentUser ? currentUser.username.charAt(0).toUpperCase() : '?';
    const idText = currentUser ? `用户 ID: ${currentUser.id}` : '点击登录以启用数据隔离';

    // Sidebar
    const sidebarName = document.getElementById('sidebarUsername');
    const sidebarAvatar = document.getElementById('sidebarAvatar');
    if (sidebarName) sidebarName.textContent = name;
    if (sidebarAvatar) sidebarAvatar.textContent = initial;

    // Settings page
    const settingsName = document.getElementById('settingsUsername');
    const settingsAvatar = document.getElementById('settingsAvatar');
    const settingsId = document.getElementById('settingsUserId');
    const settingsLoginBtn = document.getElementById('settingsLoginBtn');
    if (settingsName) settingsName.textContent = name;
    if (settingsAvatar) settingsAvatar.textContent = initial;
    if (settingsId) settingsId.textContent = idText;
    if (settingsLoginBtn) {
        if (currentUser) {
            settingsLoginBtn.textContent = '登出';
            settingsLoginBtn.onclick = logout;
        } else {
            settingsLoginBtn.textContent = '登录';
            settingsLoginBtn.onclick = () => showAuthModal('login');
        }
    }
}

// ============ API Key Functions moved to renderApiKeyList section above ============

function openNewKeyModal() {
    // Reset form for new key entry
    const sel = document.getElementById('keyProviderSelect');
    const keyIn = document.getElementById('keyValueInput');
    const urlIn = document.getElementById('keyBaseUrlInput');
    const delBtn = document.getElementById('keyDeleteBtn');
    const resultEl = document.getElementById('keyVerifyResult');
    if (sel) sel.value = 'zhipu';
    if (keyIn) keyIn.value = '';
    if (urlIn) urlIn.value = PROVIDER_DEFAULTS.zhipu.baseUrl;
    if (delBtn) delBtn.classList.add('hidden');
    if (resultEl) resultEl.classList.add('hidden');
    toggleModal('keyModal');
}
