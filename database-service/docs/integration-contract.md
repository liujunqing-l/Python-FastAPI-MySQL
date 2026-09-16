# 三方联调合同

## 浏览器认证与 TCP 内部令牌

浏览器用户先调用：

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=<密码>
```

后续浏览器查询和命令创建使用：

```http
Authorization: Bearer <access_token>
```

JWT 只给 Vue 使用。TCP 解析程序、TCP worker 和手环数据接收接口不使用 JWT，仍必须携带：

```http
X-Internal-Token: <服务端 .env 中的 INTERNAL_TOKEN>
```

`AUTH_JWT_SECRET` 与 `INTERNAL_TOKEN` 必须设置为不同的随机值。浏览器接口的设备范围由
服务端根据用户角色和 `user_device_bindings` 强制过滤，不能只靠 Vue 隐藏菜单。

## TCP 解析模块 -> 数据库服务

### F9 心跳统一事件接口（新增）

TCP worker 解码 `0xF9` 后可调用下面的统一事件接口。旧的
`POST /api/v1/health`（仅用于 `0x32` 健康帧）继续保留。

```http
POST /api/v1/ingest/events
Content-Type: application/json
X-Internal-Token: <与服务端 .env 相同的随机令牌>
```

最小请求示例：

```json
{
  "imei": "861431071299189",
  "message_id": "0xF9",
  "event_type": "heartbeat",
  "collected_at": "2026-09-09T04:00:00Z",
  "battery_type": 1,
  "battery_raw_value": 4,
  "signal_type": 0,
  "signal_raw_value": -72,
  "steps_type": 0,
  "steps_value": 1234,
  "raw_hex": "BDBDBDBDF9..."
}
```

解析程序旧字段名也兼容（`battery_value`、`signal_strength`、
`other_type`、`other_value`），但同一请求不能同时给出互相矛盾的旧名和规范名。
`message_id` 也可传数字 `249`，`message_type: 249` 可作为兼容写法；服务端统一保存
并返回 `0xF9`。

字段语义：

- `battery_type`、`signal_type`、`steps_type` 是协议中的类型字节；
- `battery_raw_value`、`signal_raw_value`、`steps_value` 原样保存；
- 只有协议明确的电量百分比类型（`battery_type=2`）才自动填充 `battery_percent`；
  四级/五级和电压类型不会被猜成百分比，无法确认时为 `null`；
- `signal_percent` 只有调用方明确提供时才保存，否则为 `null`；
- 所有时间要求带时区，保存为 UTC；`raw_hex` 必须是完整、偶数长度的十六进制文本。

响应：新记录 `201`，重复事件 `200`（`duplicate=true`），令牌错误 `401`，字段错误
`422`，数据库暂时不可用 `503`（含 `retryable=true`）。重复判定使用 `event_hash` 唯一约束。

请求：

```http
POST /api/v1/health
Content-Type: application/json
X-Internal-Token: <与服务端 .env 相同的随机令牌>
```

请求 JSON：

```json
{
  "imei": "868488079852388",
  "message_type": 50,
  "collected_at": "2026-08-31T11:20:00Z",
  "heart_rate": 92,
  "blood_oxygen": 97,
  "body_temperature": 36.7,
  "wrist_temperature": 33.9,
  "diastolic": 81,
  "systolic": 113,
  "steps": 451,
  "raw_hex": "BDBDBDBD32..."
}
```

约定：`message_type=50` 对应 TCP `0x32`；时间必须是带时区的 ISO 8601，服务端统一转为 UTC；未采集字段传 `null`；`raw_hex` 是完整帧且只能包含偶数个十六进制字符。

响应：

- `201`：首次保存，`duplicate=false`。
- `200`：重复报文，`duplicate=true`，无需再次发送。
- `401`：令牌错误。
- `422`：字段格式或数值范围错误。
- `503`：数据库暂时不可用；解析模块必须把原 JSON 写入本地待重试队列，稍后重试。

## 前端 -> 查询接口

- `GET /api/v1/devices?page=1&page_size=100`
- `GET /api/v1/health/latest?imei=<IMEI>`
- `GET /api/v1/health/history?imei=<IMEI>&start=<UTC ISO>&end=<UTC ISO>&page=1&page_size=100`
- `GET /api/v1/heartbeat/latest?imei=<IMEI>`
- `GET /api/v1/alarms?imei=<IMEI>&status=pending&start=<UTC ISO>&end=<UTC ISO>&page=1&page_size=100`
- `PATCH /api/v1/alarms/{id}/acknowledge`
- `GET /api/v1/locations/latest?imei=<IMEI>`
- `GET /api/v1/locations/history?imei=<IMEI>&start=<UTC ISO>&end=<UTC ISO>&page=1&page_size=100`
- `GET /api/v1/sleep/history?imei=<IMEI>&start=<UTC ISO>&end=<UTC ISO>&page=1&page_size=100`
- `GET /api/v1/device-config/{IMEI}`

`/api/v1/heartbeat/latest` 返回最近一条 F9 心跳的原始类型和值，以及在协议明确时才有
的百分比字段。`GET /api/v1/devices` 会把每个设备最近一条 F9 心跳的电量/信号字段
映射到设备列表；没有心跳记录时这些字段均为 `null`。

历史响应统一包含 `items`、`page`、`page_size`、`total`，按 `collected_at` 倒序。前端不要直接连接 PostgreSQL。

报警列表的 `imei`、`status`、`start` 和 `end` 均为可选过滤条件；`status` 当前支持
`pending` 和 `acknowledged`。定位历史和睡眠历史的 `start`、`end` 必填，必须携带时区，
并按半开区间 `[start, end)` 查询。最新定位返回最新一条事件；Wi-Fi/BLE 扫描事件可能
没有经纬度，此时 `resolution_status` 为 `unresolved`，经纬度必须按 JSON `null` 处理。
报警确认是幂等操作：首次将 `pending` 改为 `acknowledged`，重复调用保持原确认时间；
不存在的报警返回 `404`。没有记录的 latest/config 查询返回 `404`，非法参数返回 `422`。
报警响应中的 `measured_value` 是 PostgreSQL `NUMERIC`，当前 JSON 序列化为字符串，
前端需要按数值显示时应显式转换。

## 重试规则

网络超时、连接失败和 HTTP 503 才重试；HTTP 200（重复）和 HTTP 201（成功）都视为已处理；HTTP 401/422 应记录错误并停止对该条数据的自动重试。

## 设备命令下发（短连接）

浏览器只把命令加入数据库队列，不能直接写 TCP socket。创建命令：

```http
POST /api/v1/commands
Content-Type: application/json
```

示例（健康数据周期 5 分钟）：

```json
{
  "imei": "861431071299189",
  "command_type": "health_frequency",
  "interval_minutes": 5
}
```

支持的 `command_type` 和主要字段：

| 类型 | 协议 | 字段 |
| --- | --- | --- |
| `location_frequency` | `0x17` | `interval_minutes`，或四个 `slots` |
| `location_priority` | `0xCE01` | `priority`: `gps`、`wifi`、`ble`（最多三项） |
| `health_frequency` | `0xCE02` | `interval_minutes`（分钟范围 2–255；协议字段为 1 字节） |
| `alarm_switch` | `0xCE07/08/19/20` | `alarm_type`、`enabled`；类型 20 另需 `target=location/health` |

创建成功只表示已入队，返回 `status=pending`、`executed=false`。B2315P 是短连接设备，TCP
worker 在收到 F0 登录并回复 F1 后，同一 socket 内领取待发命令并按协议连续发送两次；设备
返回 `0xC0` 反馈后才变为 `acknowledged`/`executed=true`。如果连接在反馈前断开，租约过期后
命令回到 `pending`；达到最大重试次数后转为 `failed`，不会向前端伪造成功。

TCP worker 专用接口必须携带 `X-Internal-Token`：

```http
POST /api/v1/commands/claim
POST /api/v1/commands/{id}/sent
POST /api/v1/commands/feedback
```

`claim` 请求为 `{ "imei": "...", "worker_id": "..." }`；`feedback` 请求为
`{ "imei": "...", "message_ids": [23] }`（`0x17`）或 `[206]`（`0xCE`）。
命令状态只能由匹配的设备 `0xC0` 反馈转为 `acknowledged`。

## 数据库迁移

在 `database-service` 目录、已激活项目虚拟环境并确认 `.env` 指向目标数据库后执行：

```powershell
alembic upgrade head
```

本次新增迁移 `002_heartbeat_records`（前置版本 `001_initial`），会创建
`heartbeat_records` 表及 `event_hash`、`imei + collected_at` 索引。检查版本和表：

事件表和设备命令队列继续由 `004_device_events`、`005_device_commands` 创建；命令下发前
必须执行 `alembic upgrade head`，不要手工修改生产表结构。

```powershell
alembic current
python -c "from sqlalchemy import inspect; from app.db import engine; print(inspect(engine).get_table_names())"
```

仅对开发库回滚时可执行：

```powershell
alembic downgrade 001_initial
```
