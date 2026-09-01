# B2315P Database Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在阿里云 ECS 上交付一个可独立接收 TCP 解析模块 JSON、校验去重、保存 PostgreSQL、归档原始报文到 OSS，并向前端提供查询接口的 Python FastAPI 数据库模块。

**Architecture:** TCP 同学只负责手表 TCP 登录、心跳和 `0x32` 报文解析，并向本机 FastAPI `POST /api/v1/health` 发送统一 JSON。FastAPI 负责校验、生成事件摘要、事务写入 PostgreSQL，并把原始十六进制报文写入按日暂存文件；独立归档任务压缩文件后上传 OSS。前端只调用 FastAPI 的查询接口。

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, psycopg, pytest, httpx, oss2, Nginx, systemd。

---

## 文件结构

在新的 `database-service/` 目录中创建以下文件：

- `app/main.py`：FastAPI应用和路由注册。
- `app/config.py`：环境变量配置。
- `app/db.py`：SQLAlchemy引擎、会话和事务依赖。
- `app/models.py`：`devices`、`health_records`、`ingestion_errors`、`raw_archives`模型。
- `app/schemas.py`：写入请求、响应和查询响应模型。
- `app/services/ingestion.py`：校验后的健康数据去重、写库和暂存原始报文。
- `app/services/archive.py`：JSONL压缩、OSS上传和重试。
- `app/api/health.py`：健康数据写入和查询接口。
- `app/api/devices.py`：设备列表接口。
- `alembic.ini`、`alembic/env.py`、`alembic/versions/001_initial.py`：数据库迁移。
- `tests/test_health_ingestion.py`：写入、校验、去重测试。
- `tests/test_health_queries.py`：查询和分页测试。
- `tests/test_archive.py`：本地归档和OSS重试测试。
- `.env.example`：配置样例，不包含真实密码或密钥。
- `requirements.txt`：固定主要依赖版本范围。
- `docker-compose.dev.yml`：本地PostgreSQL测试环境。
- `README.md`：本地、阿里云部署和三方联调说明。

### Task 1: 建立 Python 项目和可测试的数据库连接

**Files:**
- Create: `database-service/requirements.txt`
- Create: `database-service/app/config.py`
- Create: `database-service/app/db.py`
- Create: `database-service/.env.example`
- Create: `database-service/docker-compose.dev.yml`
- Create: `database-service/tests/conftest.py`

- [ ] **Step 1: 创建项目目录和依赖清单**

`requirements.txt` 至少包含：

```text
fastapi==0.115.*
uvicorn[standard]==0.30.*
pydantic-settings==2.6.*
SQLAlchemy==2.0.*
alembic==1.14.*
psycopg[binary]==3.2.*
cryptography==44.*
httpx==0.28.*
pytest==8.*
pytest-asyncio==0.24.*
python-multipart==0.0.*
oss2==2.19.*
```

- [ ] **Step 2: 写入环境变量配置**

`.env.example`：

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://health_app:change-me@127.0.0.1:5432/b2315p
INTERNAL_TOKEN=replace-with-long-random-token
RAW_SPOOL_DIR=./spool
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET=b2315p-raw
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_PREFIX=raw
```

`app/config.py` 使用 `pydantic-settings` 读取这些变量，并提供 `settings` 单例。

- [ ] **Step 3: 建立 SQLAlchemy 引擎和会话依赖**

`app/db.py` 使用 `create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=10)`，定义 `SessionLocal` 和生成器 `get_db()`。测试时允许通过 `TEST_DATABASE_URL` 覆盖连接串；驱动使用 `psycopg`。

- [ ] **Step 4: 本地启动 PostgreSQL 并验证连接**

运行：

```powershell
docker compose -f docker-compose.dev.yml up -d postgres
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -c "from app.db import engine; print(engine.connect().exec_driver_sql('SELECT 1').scalar())"
```

预期输出：`1`。

- [ ] **Step 5: 提交基础项目**

```powershell
git add database-service
git commit -m "chore: initialize FastAPI database service"
```

### Task 2: 建模和数据库迁移

**Files:**
- Create: `database-service/app/models.py`
- Create: `database-service/alembic.ini`
- Create: `database-service/alembic/env.py`
- Create: `database-service/alembic/versions/001_initial.py`
- Create: `database-service/tests/test_models.py`

- [ ] **Step 1: 写模型测试**

测试必须断言四张表名称、`devices.imei`唯一约束、`health_records.event_hash`字段和 `imei + collected_at` 查询索引存在。

- [ ] **Step 2: 创建 SQLAlchemy 模型**

使用 `String(20)` 保存 IMEI，`DateTime(timezone=True)` 保存 UTC 时间，健康数值使用 `SmallInteger`、`Numeric(4,1)`，原始报文摘要使用 `String(64)`。`health_records` 包含 `collected_date`、`event_hash`、`raw_archive_id`，并建立联合索引。错误表只记录失败请求，归档表按日期和设备批次记录OSS对象。迁移使用 PostgreSQL RANGE 分区语句。

- [ ] **Step 3: 生成迁移**

配置 Alembic 从 `Base.metadata` 读取模型，编写 `001_initial.py` 创建表、索引和约束。第一版不要把分区逻辑藏在 ORM 模型中；在迁移末尾使用显式 `op.execute` 创建 PostgreSQL 未来12个月 RANGE 分区，部署时由维护脚本继续创建。

- [ ] **Step 4: 运行迁移和结构检查**

```powershell
alembic upgrade head
python -c "from sqlalchemy import inspect; from app.db import engine; print(inspect(engine).get_table_names())"
```

预期包含：`devices`, `health_records`, `ingestion_errors`, `raw_archives`。

- [ ] **Step 5: 提交模型和迁移**

```powershell
git add database-service/app/models.py database-service/alembic database-service/tests/test_models.py
git commit -m "feat: add PostgreSQL health data schema"
```

### Task 3: 定义 JSON 合同和 FastAPI 写入接口

**Files:**
- Create: `database-service/app/schemas.py`
- Create: `database-service/app/services/ingestion.py`
- Create: `database-service/app/api/health.py`
- Create: `database-service/app/main.py`
- Create: `database-service/tests/test_health_ingestion.py`

- [ ] **Step 1: 写失败测试**

覆盖以下请求：完整 JSON 返回201；同一 JSON 第二次返回200且 `duplicate=true`；IMEI错误返回422；心率超范围返回422；内部令牌错误返回401；健康字段为null仍能保存。

请求模型必须固定为：

```python
class HealthIngestRequest(BaseModel):
    imei: constr(pattern=r"^\d{14,20}$")
    message_type: Literal[50]
    collected_at: AwareDatetime
    heart_rate: int | None = Field(None, ge=20, le=250)
    blood_oxygen: int | None = Field(None, ge=0, le=100)
    body_temperature: Decimal | None = Field(None, ge=Decimal("16.0"), le=Decimal("60.0"))
    wrist_temperature: Decimal | None = Field(None, ge=Decimal("16.0"), le=Decimal("60.0"))
    diastolic: int | None = Field(None, ge=20, le=250)
    systolic: int | None = Field(None, ge=20, le=250)
    steps: int | None = Field(None, ge=0)
    raw_hex: constr(pattern=r"^(?:[0-9A-Fa-f]{2})+$")
```

- [ ] **Step 2: 实现事件摘要和事务入库**

标准化 IMEI、UTC时间和大写原始十六进制后，用 `sha256(f"{imei}|{collected_at.isoformat()}|{message_type}|{raw_hex}")` 生成 `event_hash`。在一个事务中：获取或创建设备；按唯一键检查/插入健康记录；更新 `last_seen_at`；向当天 JSONL 暂存文件追加一行。重复事件不插入第二条。

- [ ] **Step 3: 实现令牌校验和 HTTP 响应**

从 `X-Internal-Token` 读取内部令牌。成功新建返回 `201`; 重复返回 `200`; Pydantic错误返回 `422`; PostgreSQL `OperationalError` 回滚后返回 `503`，响应中包含 `retryable=true`。不要把数据库密码或原始完整报文写入错误响应。

- [ ] **Step 4: 运行写入测试**

```powershell
pytest tests/test_health_ingestion.py -q
```

预期全部通过。

- [ ] **Step 5: 提交写入接口**

```powershell
git add database-service/app database-service/tests/test_health_ingestion.py
git commit -m "feat: ingest and deduplicate health records"
```

### Task 4: 实现前端查询接口

**Files:**
- Modify: `database-service/app/api/health.py`
- Create: `database-service/app/api/devices.py`
- Modify: `database-service/app/schemas.py`
- Create: `database-service/tests/test_health_queries.py`

- [ ] **Step 1: 写查询测试**

测试设备列表、最新记录和历史分页；验证缺少 IMEI 返回422；验证结束时间早于开始时间返回422；验证 `page_size>1000` 被拒绝。

- [ ] **Step 2: 实现查询路由**

实现：

```text
GET /api/v1/devices
GET /api/v1/health/latest?imei=...
GET /api/v1/health/history?imei=...&start=...&end=...&page=1&page_size=100
```

历史查询必须按 `collected_at DESC` 排序，默认最多31天，使用 `offset/limit` 分页，响应包含 `items`, `page`, `page_size`, `total`。

- [ ] **Step 3: 运行测试**

```powershell
pytest tests/test_health_queries.py -q
```

- [ ] **Step 4: 提交查询接口**

```powershell
git add database-service/app database-service/tests/test_health_queries.py
git commit -m "feat: add device and health query APIs"
```

### Task 5: 实现 OSS 原始报文归档

**Files:**
- Create: `database-service/app/services/archive.py`
- Create: `database-service/scripts/archive_spool.py`
- Create: `database-service/tests/test_archive.py`
- Modify: `database-service/app/models.py`

- [ ] **Step 1: 写本地归档测试**

创建临时 JSONL，测试 gzip 输出、SHA-256计算、OSS客户端调用一次；模拟 OSS 异常时文件保留且 `retry_count` 增加。

- [ ] **Step 2: 实现按日压缩上传**

读取 `spool/YYYY/MM/DD/IMEI.jsonl`，写出 `.jsonl.gz`，OSS key 使用 `raw/YYYY/MM/DD/IMEI.jsonl.gz`。上传成功后写入或更新一条 `raw_archives` 批次记录，再删除本地原始 JSONL 和临时 gzip；失败不删除文件。

- [ ] **Step 3: 设置 OSS 一年生命周期**

在 README 中写明控制台操作：OSS Bucket → 生命周期规则 → 前缀 `raw/` → 过期天数365。数据库备份使用单独前缀，不使用同一删除规则。

- [ ] **Step 4: 运行测试**

```powershell
pytest tests/test_archive.py -q
```

- [ ] **Step 5: 提交归档功能**

```powershell
git add database-service/app database-service/scripts database-service/tests/test_archive.py
git commit -m "feat: archive raw TCP payloads to OSS"
```

### Task 6: 安全、运行配置和部署文档

**Files:**
- Create: `database-service/README.md`
- Create: `database-service/systemd/health-api.service`
- Create: `database-service/systemd/health-archive.timer`
- Create: `database-service/nginx/health-api.conf`
- Create: `database-service/scripts/healthcheck.py`

- [ ] **Step 1: 编写本地运行说明**

包含创建虚拟环境、复制 `.env.example`、执行 `alembic upgrade head`、运行 `uvicorn app.main:app --reload --port 8000` 和 `curl`/Postman 测试示例。

- [ ] **Step 2: 编写阿里云部署说明**

明确：安装 Python、PostgreSQL客户端和 Nginx；创建数据库和低权限角色；上传项目；配置 `.env`；执行迁移；运行 systemd；安全组仅开放 `22`（管理员IP）、`80/443`、TCP解析服务端口 `9000`；禁止公网开放 `5432` 和 `8000`。

- [ ] **Step 3: 写 systemd 配置**

FastAPI服务自动重启、工作目录固定、环境文件指向 `/opt/b2315p/database-service/.env`；归档 timer 每10分钟执行 `scripts/archive_spool.py`。

- [ ] **Step 4: 写健康检查**

`healthcheck.py` 检查 PostgreSQL `SELECT 1`、暂存目录可写和 OSS 配置完整，失败返回非零退出码，供监控使用。

- [ ] **Step 5: 提交部署配置**

```powershell
git add database-service/README.md database-service/systemd database-service/nginx database-service/scripts/healthcheck.py
git commit -m "docs: add deployment and operations configuration"
```

### Task 7: 联调和容量验收

**Files:**
- Create: `database-service/scripts/load_test.py`
- Create: `database-service/docs/integration-contract.md`

- [ ] **Step 1: 固化三方联调合同**

在 `integration-contract.md` 中复制 JSON 字段、HTTP状态码、内部令牌、重试规则和查询接口，交给 TCP 和前端同学。

- [ ] **Step 2: 编写模拟发送脚本**

脚本生成200个 IMEI，每个 IMEI 每分钟一条，支持一次性压测和持续模式；请求失败时本地写入待重试 JSONL。

- [ ] **Step 3: 运行功能验收**

```powershell
pytest -q
python scripts/load_test.py --devices 200 --burst 200
```

检查：没有重复记录、查询分页正确、设备 `last_seen_at` 更新、OSS归档状态正确。

- [ ] **Step 4: 运行故障验收**

停止 PostgreSQL 后发送请求，确认接口返回503且发送脚本保留待重试数据；恢复 PostgreSQL 后重试并确认最终只保存一条。临时阻断 OSS，确认健康记录仍可查询、暂存文件未被删除，恢复后归档成功。

- [ ] **Step 5: 完成三方联调**

先用一台真实手表连续运行24小时，再逐步增加到200台。记录接口延迟、PostgreSQL CPU/内存/磁盘占用、暂存目录大小、OSS归档数量和重复率，形成测试记录。

## 交付验收标准

- 合法 JSON 能写入 PostgreSQL；
- 重复提交不会产生重复记录；
- 错误数据有明确 401/422/503 响应；
- 前端可以按设备和时间分页查询；
- 原始报文按天压缩到 OSS，生命周期365天；
- PostgreSQL/OSS 短暂故障后可以恢复；
- 200台设备每分钟上报的模拟测试通过；
- `5432` 和 `8000` 不对公网开放；
- 有 README、迁移文件、联调合同和测试记录。
