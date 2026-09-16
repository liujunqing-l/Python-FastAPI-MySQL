# B2315P 数据库接收服务

这个服务接收 TCP 解析模块生成的标准 JSON，校验后写入 PostgreSQL，并把原始 TCP 十六进制报文按天压缩归档到阿里云 OSS。

```text
B2315P 手环 -> TCP 解析模块 -> POST /api/v1/health -> PostgreSQL
                                             └-> spool/YYYY/MM/DD/*.jsonl -> OSS
前端       -> GET /api/v1/devices、/health/latest、/health/history
TCP F9    -> POST /api/v1/ingest/events -> heartbeat_records
```

浏览器首次访问需要登录：`POST /api/v1/auth/login` 返回 JWT，之后查询和命令创建请求携带
`Authorization: Bearer <JWT>`。JWT 只用于浏览器用户；TCP 解析程序和 worker 继续使用
`.env` 中的 `INTERNAL_TOKEN`，两者必须是不同的随机字符串。

## 1. 本地运行

需要 Python 3.12（本机开发也可使用 3.9）、PostgreSQL 16。复制环境变量模板并填写数据库地址和内部令牌：

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

如果使用项目提供的 Docker 开发数据库：

```powershell
docker compose -f docker-compose.dev.yml up -d postgres
```

浏览器打开 `http://127.0.0.1:8000/docs` 可查看 Swagger 接口文档。

## 2. 查询接口

- `GET /api/v1/devices?page=1&page_size=100`
- `GET /api/v1/health/latest?imei=868488079852388`
- `GET /api/v1/health/history?imei=868488079852388&start=2026-08-31T00:00:00Z&end=2026-09-01T00:00:00Z&page=1&page_size=100`
- `GET /api/v1/heartbeat/latest?imei=868488079852388`
- `GET /api/v1/alarms?imei=<IMEI>&status=pending&page=1&page_size=100`
- `PATCH /api/v1/alarms/{id}/acknowledge`
- `GET /api/v1/locations/latest?imei=<IMEI>`
- `GET /api/v1/locations/history?imei=<IMEI>&start=<UTC ISO>&end=<UTC ISO>&page=1&page_size=100`
- `GET /api/v1/sleep/history?imei=<IMEI>&start=<UTC ISO>&end=<UTC ISO>&page=1&page_size=100`
- `GET /api/v1/device-config/<IMEI>`
- `GET /api/v1/commands?imei=<IMEI>&status=pending&page=1&page_size=100`

认证接口：

- `POST /api/v1/auth/login`（`application/x-www-form-urlencoded`，字段 `username`、`password`）
- `GET /api/v1/auth/me`（Bearer JWT）

`admin` 可以查看全部设备；`operator` 和 `viewer` 只能查看已经绑定的设备。`operator`
可以确认报警和创建设备命令，`viewer` 只读。未登录、令牌过期返回 `401`，角色不足返回
`403`。初始化管理员运行 `scripts/create_admin.py --username admin`，按提示输入不回显的密码，
不要把密码写入命令行或仓库。

浏览器通过 `POST /api/v1/commands` 把定位/健康周期、定位优先级和报警开关加入命令队列；
TCP worker 只在手环短连接登录后领取并发送，收到 `0xC0` 回执后命令才会显示为已执行。

F9 心跳写入接口为 `POST /api/v1/ingest/events`，字段合同和示例见
[`docs/integration-contract.md`](docs/integration-contract.md)。旧的健康写入接口
`POST /api/v1/health` 保持兼容。

历史接口按采集时间倒序返回，单次最多 1000 条；时间必须带时区且 `end` 晚于 `start`。

## 3. OSS 归档

FastAPI 写入成功后，原始报文暂存在 `RAW_SPOOL_DIR`。每日定时执行：

```bash
python scripts/archive_spool.py
```

文件 `spool/2026/08/31/868488079852388.jsonl` 会压缩并上传为 `raw/2026/08/31/868488079852388.jsonl.gz`。上传成功才删除本地文件；失败会保留文件并在 `raw_archives.retry_count` 中累计重试次数。

OSS 控制台请给 `raw/` 前缀设置 365 天生命周期规则。数据库备份使用独立的 OSS 前缀，不要与原始报文共用删除规则。

## 4. 阿里云 Ubuntu 部署

建议把代码放在 `/opt/b2315p/database-service`，虚拟环境放在同目录 `.venv`，环境文件放在 `.env`（权限 `600`）。创建 PostgreSQL 数据库和低权限账号后填写：

```dotenv
DATABASE_URL=postgresql+psycopg://health_app:密码@127.0.0.1:5432/b2315p
INTERNAL_TOKEN=随机长字符串
RAW_SPOOL_DIR=/var/lib/b2315p/spool
```

执行 `alembic upgrade head` 后，安装 `systemd/health-api.service` 和 `systemd/health-archive.timer`，再运行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now health-api.service
sudo systemctl enable --now health-archive.timer
sudo systemctl status health-api.service health-archive.timer
```

Nginx 只代理 80/443 到 `127.0.0.1:8000`；TCP 解析服务使用独立的 8825 端口（当前手环已配置并验证）。安全组不要向公网开放 PostgreSQL 5432 或 FastAPI 8000。

## 5. 三方联调顺序

1. 先用模拟 JSON 验证写入、重复提交和查询接口。
2. 前端根据查询接口完成页面。
3. TCP 同学将解析结果按 `docs/integration-contract.md` 调用写入接口。
4. 先接一块真实手环运行 4 小时，再扩展到三块和 200 块。
