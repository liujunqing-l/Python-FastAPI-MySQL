# 前端 V2 兼容与发布记录

## 结论

`VUE-v2/vue-app` 是同学交付的独立前端原稿。它可以单独构建，但不能直接替换正式页面：原稿没有当前生产版本使用的登录页、JWT 会话、角色权限和完整路由，也会遗漏定位、睡眠、报警、设备设置和指令等已接通功能。

正式发布版本继续使用 `vue前端源码/vue-app` 作为基础。该版本已经保留：

- 管理员登录、退出登录和 JWT 请求头；
- 角色权限和设备绑定范围；
- PostgreSQL 中的真实设备、健康、定位、睡眠和报警查询；
- 设备指令和健康上传周期设置；
- 真实错误、空数据和缺失字段的显示规则。

V2 原稿只作为供应方交付物保存到 `codex/frontend-v2-import` 分支，便于审阅和以后挑选视觉改动。没有把 V2 的认证、API 或路由代码复制到正式版本。

## 本地验收

正式候选分支的前端目录：

```text
vue前端源码/vue-app
```

在该目录执行：

```powershell
pnpm install --frozen-lockfile
pnpm test
pnpm run build
```

后端目录 `database-service` 执行：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

只有前后端测试和构建都通过，才允许打包 `dist` 部署到云服务器。

## 后续 V3、V4 处理规则

每次收到新前端时：

1. 原稿复制到独立的 `codex/frontend-vN-import` 分支，不覆盖正式目录。
2. 检查登录、JWT、路由、权限、API 地址和真实数据字段。
3. 只把通过检查的页面样式和交互合入 `codex/frontend-v2-integration` 的正式代码。
4. 重跑前端测试、后端测试和生产构建。
5. 备份云端旧 `dist` 后再发布；验收失败立即恢复备份。

## 发布保护

禁止把供应方原稿直接复制到 `/var/www/b2315p/frontend/dist`。生产目录只接收经过本地构建和验收的正式候选版本。Git 分支、提交和云端 `dist` 备份共同作为回滚点。
