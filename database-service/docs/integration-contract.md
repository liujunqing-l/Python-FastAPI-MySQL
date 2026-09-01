# 三方联调合同

## TCP 解析模块 -> 数据库服务

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

历史响应统一包含 `items`、`page`、`page_size`、`total`，按 `collected_at` 倒序。前端不要直接连接 PostgreSQL。

## 重试规则

网络超时、连接失败和 HTTP 503 才重试；HTTP 200（重复）和 HTTP 201（成功）都视为已处理；HTTP 401/422 应记录错误并停止对该条数据的自动重试。
