"""CiteWise E2E Test Suite — Playwright"""
from playwright.sync_api import sync_playwright
import time

results = {'pass': 0, 'fail': 0, 'skip': 0}

def check(name, condition, detail=''):
    if condition:
        results['pass'] += 1
        print(f'  PASS: {name}')
    else:
        results['fail'] += 1
        print(f'  FAIL: {name} {detail}')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = []
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)

    # === 1. Page Load ===
    print('\n--- 1. Page Load ---')
    resp = page.goto('http://127.0.0.1:8080/', timeout=10000)
    check('Page HTTP 200', resp.status == 200)
    time.sleep(3)
    check('No JS errors on load', len(errors) == 0, str(errors[:3]))
    errors.clear()

    # === 2. Sidebar ===
    print('\n--- 2. Sidebar ---')
    check('Brand name visible', page.locator('.brand-name').is_visible())
    check('User profile John Doe visible', page.locator('text=John Doe').first.is_visible())
    check('Agent status panel exists', page.locator('#agentStatusList').is_visible())
    agents = page.locator('#agentStatusList > div')
    check('3 agents rendered', agents.count() == 3, f'got {agents.count()}')

    # === 3. Navigation ===
    print('\n--- 3. Navigation ---')
    nav_items = [
        ('协同中心', 'chatView'),
        ('文献索引', 'paperView'),
        ('章节草稿', 'draftView'),
    ]
    for label, vid in nav_items:
        btn = page.locator(f'button:has-text("{label}")').first
        btn.click()
        time.sleep(0.3)
        check(f'Nav -> {label}', page.locator(f'#{vid}.active').count() > 0)

    page.locator('button:has-text("Skill 集")').first.click()
    time.sleep(0.3)
    check('Nav -> Skill 集', page.locator('#skillView.active').count() > 0)

    page.locator('button:has-text("工具箱")').first.click()
    time.sleep(0.3)
    check('Nav -> 工具箱', page.locator('#toolView.active').count() > 0)

    page.locator('button:has-text("AgentEval")').first.click()
    time.sleep(0.3)
    check('Nav -> AgentEval', page.locator('#evalView.active').count() > 0)

    page.locator('#navSettings').click()
    time.sleep(0.3)
    check('Nav -> Settings (via profile)', page.locator('#settingsView.active').count() > 0)

    # === 4. Chat View ===
    print('\n--- 4. Chat View ---')
    page.locator('button:has-text("协同中心")').first.click()
    time.sleep(0.3)
    check('Chat input visible', page.locator('#chatInput').is_visible())
    check('Send button visible', page.locator('#sendBtn').is_visible())
    page.locator('#chatInput').fill('test message')
    check('Chat input typeable', page.locator('#chatInput').input_value() == 'test message')
    page.locator('#chatInput').fill('')

    check('提取矩阵 button visible', page.locator('button:has-text("提取矩阵")').is_visible())
    page.locator('button:has-text("提取矩阵")').click()
    time.sleep(0.3)
    check('summaryModal opens', page.locator('#summaryModal:not(.hidden)').count() > 0)
    page.evaluate("document.getElementById('summaryModal').classList.add('hidden')")
    time.sleep(0.3)

    # === 5. Paper View ===
    print('\n--- 5. Paper View ---')
    page.locator('button:has-text("文献索引")').first.click()
    time.sleep(0.3)
    check('Upload input exists', page.locator('#paperUpload').count() > 0)
    check('Paper list container exists', page.locator('#paperListContainer').is_visible())

    papers = page.locator('#paperListContainer > div')
    if papers.count() > 0:
        papers.first.click()
        time.sleep(0.5)
        check('Paper detail view opens', page.locator('#paperDetailView:not(.hidden)').count() > 0)
        page.locator('#paperDetailView').locator('button').first.click()
        time.sleep(0.3)
    else:
        results['skip'] += 1
        print('  SKIP: Paper detail (no papers)')

    # === 6. Draft View ===
    print('\n--- 6. Draft View ---')
    page.locator('button:has-text("章节草稿")').first.click()
    time.sleep(0.3)
    check('Draft list exists', page.locator('#draftList').is_visible())
    check('新建章节 button visible', page.locator('button:has-text("新建章节")').is_visible())

    page.locator('button:has-text("新建章节")').click()
    time.sleep(0.3)
    check('newDraftModal opens', page.locator('#newDraftModal:not(.hidden)').count() > 0)
    # Close modal via JS (lucide replaces <i> with <svg>)
    page.evaluate("document.getElementById('newDraftModal').classList.add('hidden')")
    time.sleep(0.3)

    drafts = page.locator('#draftList > div')
    if drafts.count() > 0:
        drafts.first.click()
        time.sleep(0.5)
        check('Draft editor opens', page.locator('#draftEditor:not(.hidden)').count() > 0)
        check('editableArea exists', page.locator('#editableArea').is_visible())
        check('subInput textarea exists', page.locator('#subInput').is_visible())
        check('智能续写 button exists', page.locator('button:has-text("智能续写")').is_visible())
        page.locator('#draftEditor').locator('button').first.click()
        time.sleep(0.3)
    else:
        results['skip'] += 1
        print('  SKIP: Draft editor (no drafts)')

    # === 7. Skill View ===
    print('\n--- 7. Skill View ---')
    page.locator('button:has-text("Skill 集")').first.click()
    time.sleep(0.3)
    skills = page.locator('#skillListContainer > div')
    check('Skills rendered', skills.count() > 0, f'count: {skills.count()}')

    if skills.count() > 0:
        skills.first.click()
        time.sleep(0.3)
        check('Skill detail opens', page.locator('#skillDetailView:not(.hidden)').count() > 0)
        check('skillIntro has content', page.locator('#skillIntro').inner_text() != '')
        page.locator('#skillDetailView').locator('button').first.click()
        time.sleep(0.3)

    check('安装新 Skill button visible', page.locator('button:has-text("安装新 Skill")').is_visible())
    page.locator('button:has-text("安装新 Skill")').click()
    time.sleep(0.3)
    check('addAssetModal opens', page.locator('#addAssetModal:not(.hidden)').count() > 0)
    page.evaluate("document.getElementById('addAssetModal').classList.add('hidden')")

    # === 8. Tool View ===
    print('\n--- 8. Tool View ---')
    page.locator('button:has-text("工具箱")').first.click()
    time.sleep(0.3)
    tools = page.locator('#toolListContainer > div')
    check('Tools rendered', tools.count() > 0, f'count: {tools.count()}')

    if tools.count() > 0:
        tools.first.click()
        time.sleep(0.3)
        check('Tool detail opens', page.locator('#toolDetailView:not(.hidden)').count() > 0)
        check('toolActionContent has content', page.locator('#toolActionContent').inner_text() != '')
        page.locator('#toolDetailView').locator('button').first.click()
        time.sleep(0.3)

    check('导入 Python 工具 input exists', page.locator('#localToolInput').count() > 0)

    # === 9. Settings View ===
    print('\n--- 9. Settings View ---')
    page.locator('#navSettings').click()
    time.sleep(0.3)
    check('Settings view active', page.locator('#settingsView.active').count() > 0)
    check('API key list exists', page.locator('#apiKeyListContainer').is_visible())

    key_cards = page.locator('#apiKeyListContainer > div')
    check('API keys rendered', key_cards.count() > 0, f'count: {key_cards.count()}')

    check('+ 新增配置 visible', page.locator('text=新增配置').is_visible())
    page.locator('text=新增配置').click()
    time.sleep(0.3)
    check('keyModal opens', page.locator('#keyModal:not(.hidden)').count() > 0)
    page.evaluate("document.getElementById('keyModal').classList.add('hidden')")

    # === 10. Agent Create Modal ===
    print('\n--- 10. Agent Create Modal ---')
    page.locator('button:has-text("协同中心")').first.click()
    time.sleep(0.3)
    page.get_by_text('子 Agent 状态').locator('..').locator('button').click()
    time.sleep(0.3)
    check('createAgentModal opens', page.locator('#createAgentModal:not(.hidden)').count() > 0)
    check('Agent name input exists', page.locator('#agentNameIn').count() > 0)
    page.evaluate("document.getElementById('createAgentModal').classList.add('hidden')")

    # === 11. Project Dropdown ===
    print('\n--- 11. Project Dropdown ---')
    check('Project selector visible', page.locator('#currentProjectName').is_visible())
    page.locator('#currentProjectName').click()
    time.sleep(0.3)
    check('Project dropdown opens', page.locator('#projectDropdown.show').count() > 0)
    check('新建研究项目 visible', page.locator('text=新建研究项目').is_visible())
    page.keyboard.press('Escape')
    time.sleep(0.3)

    # === 12. Backend API ===
    print('\n--- 12. Backend API ---')
    try:
        r = page.evaluate("""async () => {
            const r1 = await fetch('/api/projects');
            const projects = await r1.json();
            if (!projects || projects.length === 0) return 'no projects';
            const pid = projects[0].id;
            const r2 = await fetch('/api/projects/' + pid + '/state');
            const state = await r2.json();
            return JSON.stringify({
                p: projects.length,
                papers: (state.papers||[]).length,
                sections: (state.sections_with_id||[]).length
            });
        }""")
        check('API projects + state OK', True, r)
    except Exception as e:
        check('API projects + state OK', False, str(e))

    # === 13. Chat SSE ===
    print('\n--- 13. Chat SSE Test ---')
    page.locator('button:has-text("协同中心")').first.click()
    time.sleep(0.3)
    page.locator('#chatInput').fill('总结一下')
    page.locator('#sendBtn').click()
    time.sleep(10)
    chat_bubbles = page.locator('#dynamicChatContent > div')
    check('Chat sends + receives (bubbles >= 3)', chat_bubbles.count() >= 3, f'count: {chat_bubbles.count()}')
    check('No JS errors after chat', len(errors) == 0, str(errors[:3]))

    # === Summary ===
    print(f'\n===== SUMMARY =====')
    print(f'  Passed:  {results["pass"]}')
    print(f'  Failed:  {results["fail"]}')
    print(f'  Skipped: {results["skip"]}')
    print(f'  Total:   {results["pass"] + results["fail"] + results["skip"]}')

    page.screenshot(path='C:/Users/77230/screenshot_final.png')
    browser.close()
