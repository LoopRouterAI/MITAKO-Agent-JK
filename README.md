# MITAKO Agent — 虾淘 AI 客服 + Companion 双系统

单仓库交付 **两套产品**（智能客服 + Companion 陪伴），Windows 本地一键启动。

---

## 从这里开始

| 你是… | 先读 | 再运行 |
|--------|------|--------|
| **开发** | **[开发上手.md](./开发上手.md)** | `setup_venv.bat` → `一键启动-Windows.bat` |
| **测试 / 验收** | **[测试指南.md](./测试指南.md)** | `双系统测试-Windows.bat` |

---

## 两套系统一览

| 系统 | 前台 | 后台 |
|------|------|------|
| **A · 智能客服** | http://127.0.0.1:8000/ | `/desk` `/admin` |
| **B · Companion** | http://127.0.0.1:8000/companion | `/companion-desk` |

---

## 根目录常用脚本

```bat
setup_venv.bat                  REM 首次：Python 环境
一键启动-Windows.bat            REM 日常开发
双系统测试-Windows.bat          REM 测试主菜单
双系统测试-全链路-Windows.bat   REM 发版前：E2E + 联调
```

---

## 文档

- [docs/README.md](./docs/README.md) — 完整文档索引
- [docs/delivery/](./docs/delivery/) — 部署、对接、验收
- [docs/CodeWiki.md](./docs/CodeWiki.md) — 架构与调用链

---

## 打包说明

收到 ZIP 后：解压 → 读 `开发上手.md` → `setup_venv.bat` → `npm install` → 配置 `.env` → `一键启动-Windows.bat`。  
打包清单见 [打包说明.md](./打包说明.md)（维护方使用）。
