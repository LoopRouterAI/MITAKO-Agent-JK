# 部署指南（双系统合一进程）

## 1. 环境要求

| 项 | 版本 |
|----|------|
| OS | Windows 11 / Server 2019+ |
| Python | 3.11+（项目 `venv`） |
| Node | 18+（`npm run build`） |
| Redis | 可选；生产 + 多实例 **强烈建议** |
| GPU | 非必须（LLM 走云端 API） |

## 2. 首次部署

```bat
cd MITAKO_Agent
setup_venv.bat          REM 若已有 venv 可跳过
npm install
npm run build
python scripts/seed_auth.py
```

## 3. 开发 / UAT 启动

```bat
一键启动-Windows.bat
```

默认 env：

```env
APP_PORT=8000
HANDOFF_BACKEND=hybrid
CHATWOOT_MOCK=1
MITAKO_AUTH_REQUIRED=0
MITAKO_SSO_DEMO=0
```

## 4. 生产启动（摘要）

```env
MITAKO_AUTH_REQUIRED=1
MITAKO_JWT_SECRET=<随机长密钥>
MITAKO_SSO_DEMO=0
REDIS_HOST=<redis>
HANDOFF_BACKEND=hybrid
CHATWOOT_MOCK=0
CHATWOOT_BASE_URL=https://im.<交付域名>
ALLOW_PORT_FALLBACK=0
```

完整清单：[production-checklist.md](../security/production-checklist.md)

## 5. 端口

| 端口 | 服务 |
|------|------|
| 8000 | MITAKO 主服务（五端 SPA + API） |
| 9101 | 甲方模拟 IdP（联调实验室，可选） |
| 9102 | 甲方模拟 Chatwoot（联调实验室，可选） |
| 9103 | 甲方模拟业务 API（联调实验室，可选） |

## 6. 静态资源

`npm run build` → `dist/`（`index.html` `desk.html` `admin.html` `companion.html` `companion-desk.html`）

## 7. 数据文件

| 路径 | 内容 |
|------|------|
| `data/handoff.db` | 转人工会话 |
| `data/admin.db` | 坐席、审批 |
| `data/companion.db` | Companion |
| `data/auth.db` | 账号、租户 |

备份：停机复制 `data/` 目录。

## 8. 我方 vs 甲方

| 我方全包 | 甲方配合 |
|----------|----------|
| MITAKO 应用部署 | SSO IdP 凭据 / Groups |
| Chatwoot 实例部署 | UAT 账号、验收签字 |
| 联调实验室模拟终端 | 业务 API 契约评审（后续） |
