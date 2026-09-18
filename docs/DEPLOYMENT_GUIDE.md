# CiteWise 部署教程（新手版）

> 从零开始，一步一步把 CiteWise 部署到互联网上。
> 你不需要任何服务器知识，只需要一台能上网的电脑。

---

## 整体架构（先看一眼）

```
你的浏览器
    │
    ├── 前端（Vercel，免费）── 显示网页界面
    │   └── 网址类似：https://citewise.vercel.app
    │
    └── 后端（Render，免费）── 处理数据、AI 对话
        └── 网址类似：https://citewise-backend.onrender.com
```

前端和后端分别部署在两个平台上，互不干扰。

---

## 第一步：准备工作（注册账号）

你需要注册 **3 个账号**，全部免费：

| 账号 | 网址 | 用途 |
|------|------|------|
| **GitHub** | https://github.com/signup | 存放代码 |
| **Render** | https://render.com | 部署后端 |
| **Vercel** | https://vercel.com | 部署前端 |

### 1.1 注册 GitHub

1. 打开 https://github.com/signup
2. 填写用户名、邮箱、密码
3. 完成邮箱验证
4. （可选）下载 GitHub Desktop：https://desktop.github.com

### 1.2 注册 Render

1. 打开 https://render.com
2. 点击 **Get Started**
3. 选择 **Sign up with GitHub**（用 GitHub 账号直接登录）
4. 授权 Render 访问你的 GitHub

### 1.3 注册 Vercel

1. 打开 https://vercel.com
2. 点击 **Start Deploying**
3. 选择 **Continue with GitHub**
4. 授权 Vercel 访问你的 GitHub

---

## 第二步：把代码推到 GitHub

### 2.1 确认 Git 已安装

打开终端（Windows 按 Win+R，输入 `cmd`），输入：

```bash
git --version
```

如果显示版本号（如 `git version 2.43.0`），说明已安装。
如果提示"不是内部命令"，去 https://git-scm.com 下载安装。

### 2.2 在 GitHub 上创建仓库

1. 打开 https://github.com/new
2. **Repository name** 填：`CiteWise`
3. 选择 **Private**（私有，别人看不到你的代码）
4. **不要** 勾选 "Add a README file"
5. 点击 **Create repository**

### 2.3 推送代码到 GitHub

在 CiteWise 项目目录打开终端，执行：

```bash
cd C:\Users\77230\CiteWise

# 添加远程仓库（把 kizzzz 换成你的 GitHub 用户名）
git remote set-url origin https://github.com/kizzzz/CiteWise.git

# 添加所有文件
git add .

# 提交
git commit -m "feat: deploy config for Vercel + Render"

# 推送
git push -u origin main
```

如果弹出登录框，用 GitHub 账号登录即可。

> **注意**：`.gitignore` 已经排除了 `.env` 文件（包含 API Key），
> 所以你的密钥不会被推送到 GitHub。

---

## 第三步：部署后端到 Render（先部署后端）

### 3.1 创建新的 Web Service

1. 登录 https://dashboard.render.com
2. 点击 **New** → **Web Service**
3. 选择 **Build and deploy from a Git repository**
4. 点击 **Connect** 你的 GitHub 账号
5. 找到 **CiteWise** 仓库，点击 **Connect**

### 3.2 配置服务

填写以下信息：

| 字段 | 填写内容 |
|------|----------|
| **Name** | `citewise-backend` |
| **Region** | `Oregon, USA`（或离你最近的） |
| **Branch** | `main` |
| **Runtime** | **Docker** |
| **Instance Type** | **Free** |

### 3.3 设置环境变量

在页面下方找到 **Environment Variables**，添加以下变量：

| Key | Value | 说明 |
|-----|-------|------|
| `OPENAI_API_KEY` | `你的智谱API Key` | 在 https://open.bigmodel.cn 获取 |
| `OPENAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4/` | 智谱 API 地址 |
| `LLM_MODEL` | `glm-4.7` | 使用的模型 |
| `EMBEDDING_MODEL` | `embedding-3` | Embedding 模型 |
| `EMBEDDING_DIMENSION` | `2048` | 向量维度 |

> **如何获取智谱 API Key**：
> 1. 打开 https://open.bigmodel.cn
> 2. 注册并登录
> 3. 进入「API 密钥」页面
> 4. 点击「创建 API 密钥」，复制生成的 Key

### 3.4 开始部署

1. 点击页面底部的 **Create Web Service**
2. 等待构建完成（大约 5-10 分钟）
3. 构建成功后，页面顶部会显示你的后端 URL：
   ```
   https://citewise-backend-xxxx.onrender.com
   ```

### 3.5 验证后端

在浏览器中打开：
```
https://citewise-backend-xxxx.onrender.com/docs
```
如果看到 FastAPI 的自动文档页面，说明后端部署成功！

---

## 第四步：更新前端的后端地址

上一步你拿到了后端的 URL（如 `https://citewise-backend-xxxx.onrender.com`），
需要把它填到前端代码里。

### 4.1 修改 app.js

打开文件 `C:\Users\77230\CiteWise\static\js\app.js`，找到第 4-6 行：

```javascript
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? ''  // 开发环境：同源
    : 'https://citewise-backend.onrender.com';  // ← 改成你的实际后端地址
```

把 `https://citewise-backend.onrender.com` 改成你在第三步拿到的实际地址。

### 4.2 提交并推送

```bash
cd C:\Users\77230\CiteWise
git add static/js/app.js
git commit -m "fix: update backend URL for production"
git push
```

---

## 第五步：部署前端到 Vercel

### 5.1 导入项目

1. 登录 https://vercel.com/dashboard
2. 点击 **Add New...** → **Project**
3. 找到 **CiteWise** 仓库，点击 **Import**

### 5.2 配置项目

| 字段 | 填写内容 |
|------|----------|
| **Project Name** | `citewise` |
| **Framework Preset** | **Other** |
| **Root Directory** | 点击 Edit，输入 `static` |
| **Build Command** | 留空 |
| **Output Directory** | 留空（使用 Root Directory） |

> **Root Directory 设置为 `static` 非常重要！**
> 这样 Vercel 就会直接把 `static/` 目录作为网站根目录。

### 5.3 部署

1. 点击 **Deploy**
2. 等待约 1 分钟
3. 部署成功！你会看到：
   ```
   🎉 Congratulations!
   https://citwise-xxxx.vercel.app
   ```

### 5.4 （可选）设置自定义域名

1. 在 Vercel 项目页面 → **Settings** → **Domains**
2. 输入你想要的域名（如果有的话）
3. 没有域名也没关系，Vercel 提供的 `.vercel.app` 域名可以直接用

---

## 第六步：验证整个系统

### 6.1 打开前端

在浏览器中访问你的 Vercel 地址：
```
https://citwise-xxxx.vercel.app
```

你应该能看到 CiteWise 的界面。

### 6.2 创建项目

1. 在左侧边栏点击 **新建项目**
2. 输入项目名称，点击创建

### 6.3 上传论文

1. 点击 **论文** 标签
2. 上传一个 PDF 文件
3. 等待处理完成

### 6.4 开始对话

1. 点击 **对话** 标签
2. 输入问题，如："这篇论文的主要贡献是什么？"
3. 等待 AI 回复

如果以上步骤都能正常工作，**恭喜你，部署成功！**

---

## 常见问题排查

### Q1: 后端冷启动太慢（30-60秒）

**原因**：Render 免费层 15 分钟无请求后会休眠。

**解决方案**（三选一）：
1. **接受它**：首次访问等一下就好，后续请求很快
2. **定时唤醒**：去 https://cron-job.org 注册免费账号，设置每 14 分钟 ping 一次你的后端 URL
3. **升级付费**：Render $7/月，不休眠

### Q2: 后端 API 返回 500 错误

1. 去 Render 控制台查看 **Logs**（日志）
2. 最常见的原因是 `OPENAI_API_KEY` 没有设置或已过期
3. 检查智谱账户余额是否充足

### Q3: 前端能打开但无法对话

1. 打开浏览器 **开发者工具**（按 F12）
2. 切到 **Console**（控制台）标签
3. 看看有没有红色错误信息
4. 最常见的原因是后端地址没填对

### Q4: 前端页面空白

1. 确认 Vercel 的 **Root Directory** 设置为 `static`
2. 确认 GitHub 仓库的 `static/` 目录有 `index.html`

### Q5: 上传 PDF 失败

1. 确认 PDF 文件小于 50MB
2. 查看后端日志是否有错误
3. Render 免费层内存有限（512MB），太大的 PDF 可能处理不了

### Q6: 数据丢失了

**原因**：Render 免费层没有持久化磁盘，重启后数据会丢失。

**解决方案**：
- 免费层只适合演示和面试展示
- 每次使用前重新上传 PDF 即可
- 如需持久化，升级 Render 付费层（$7/月）

---

## 费用总结

| 平台 | 费用 | 限制 |
|------|------|------|
| **Vercel** | 免费 | 100GB 带宽/月 |
| **Render** | 免费 | 750 小时/月，512MB 内存，15分钟休眠 |
| **智谱 API** | 按量付费 | 新用户有免费额度 |

**每月总费用：0 元**（智谱新用户额度内）

---

## 面试展示建议

1. **提前准备好**：面试前 5 分钟访问一次后端 URL 唤醒服务
2. **准备好 Demo 流程**：
   - 创建项目 → 上传 PDF → 提问 → 展示 AI 回复
3. **备用方案**：同时准备本地运行的 Demo（以防网络问题）
   ```bash
   cd C:\Users\77230\CiteWise
   python run.py
   # 浏览器打开 http://localhost:8080
   ```
