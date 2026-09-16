# B2315P 登录与设备权限部署说明

本次认证改动只影响浏览器用户，不改变 TCP 解析程序与手环的通信方式。

```text
Vue 浏览器 -- Authorization: Bearer <JWT> --> FastAPI 查询/命令接口
TCP worker -- X-Internal-Token ------------> FastAPI 接收/队列接口
```

`AUTH_JWT_SECRET` 和 `INTERNAL_TOKEN` 必须是两条不同的随机长字符串。TCP
程序不能使用 JWT，浏览器也不应携带内部令牌。

## 本地初始化

在 `database-service` 目录、已激活 `.venv` 且 `.env` 已指向开发库时执行：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填写 DATABASE_URL、INTERNAL_TOKEN、AUTH_JWT_SECRET
alembic upgrade head
python scripts/create_admin.py --username admin --display-name '系统管理员'
uvicorn app.main:app --reload --port 8000
```

首次登录：

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=...
```

响应中的 `access_token` 仅供 Vue 保存到会话存储，后续浏览器请求使用：

```http
Authorization: Bearer <access_token>
```

## 角色规则

| 角色 | 数据查询 | 报警确认 | 命令下发 | 用户/设备绑定管理 |
| --- | --- | --- | --- | --- |
| `admin` | 全部设备 | 可以 | 可以 | 预留给管理接口 |
| `operator` | 已绑定设备 | 可以 | 可以 | 不可以 |
| `viewer` | 已绑定设备 | 不可以 | 不可以 | 不可以 |

未绑定设备不会通过浏览器查询接口返回。TCP 内部接收接口仍只验证
`X-Internal-Token`，不执行浏览器角色过滤。

## 阿里云生产发布顺序

1. 备份 PostgreSQL 数据库和 `/var/lib/b2315p/spool`。
2. 将本地代码复制到新的发布目录，保留当前线上 `.env` 和 TCP 程序。
3. 在 API 服务 `.env` 设置：

   ```dotenv
   APP_ENV=production
   AUTH_JWT_SECRET=<新的随机长字符串>
   AUTH_JWT_EXPIRE_SECONDS=3600
   ```

   `INTERNAL_TOKEN` 必须继续填写线上 TCP 程序当前使用的值；不要在同一次发布中轮换它。
4. 激活 API 虚拟环境，执行 `alembic upgrade head`，确认版本为
   `007_alarm_rules`。
5. 执行 `scripts/create_admin.py` 创建管理员，按提示输入不回显的密码。不要把密码写入命令行、仓库或部署文档。
6. 重启 FastAPI 服务，检查 `/healthz`、登录接口和一条带 JWT 的设备查询。
7. 部署 Vue 构建产物，确认登录后可以看到绑定范围内的设备。
8. 最后验证 TCP worker 仍能用内部令牌调用 `/api/v1/ingest/events`、命令
   `claim/sent/feedback` 接口；不要让手环或 TCP worker 改用 JWT。

生产环境不要开放 PostgreSQL `5432` 或 FastAPI 内部端口 `8000` 到公网，浏览器只通过
Nginx 的 `80/443` 访问；TCP 手环端口继续按现网 `8825` 配置。

## 管理接口

管理员登录后，Vue 管理页面使用以下接口完成账号、绑定、设备和报警规则管理：

- `GET /api/v1/roles`
- `GET/POST /api/v1/accounts`
- `PATCH /api/v1/accounts/{id}`
- `PUT /api/v1/accounts/{id}/bindings`，请求体为 `{ "imeis": ["..."] }`
- `POST /api/v1/devices`
- `PATCH /api/v1/devices/{imei}`
- `PATCH /api/v1/devices/batch`
- `GET/POST /api/v1/alarm-rules`
- `PATCH/DELETE /api/v1/alarm-rules/{id}`

以上接口均使用浏览器 JWT；`operator` 和 `viewer` 不能调用管理员接口。数据库升级必须执行
`alembic upgrade head`，当前头版本为 `007_alarm_rules`。
