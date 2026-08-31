# B2315P 数据库接收与保存模块设计

## 1. 目标与范围

本模块负责接收 TCP 解析模块生成的标准 JSON，完成数据校验、去重、MySQL 持久化、原始报文归档，并向前端提供查询接口。

本模块不负责：

- 监听手环 TCP 连接；
- 处理 F0/F1 登录和 F9 心跳；
- 解析 BDBDBDBD 二进制帧；
- 实现前端页面。

部署规模为 200 台 B2315P，每台每分钟上报一次。理论数据量为每天 288,000 次、每年 105,120,000 次上传。

## 2. 技术选型

- Python 3.12；
- FastAPI；
- Pydantic；
- SQLAlchemy 2；
- Alembic 数据库迁移；
- MySQL 8；
- 阿里云 OSS；
- Nginx；
- systemd 或 Docker Compose 管理进程。

课程项目第一版不引入 RabbitMQ、Redis、Celery和微服务注册中心。200台设备的平均写入约为每秒3.33次，FastAPI和MySQL可以直接处理。

## 3. 系统边界与数据流

推荐将 TCP 服务、FastAPI、MySQL 和 Nginx 部署在同一台阿里云 ECS：

```text
B2315P手表
    ↓ TCP :9000
TCP解析模块
    ↓ HTTP JSON（127.0.0.1:8000）
FastAPI数据库模块
    ├─→ MySQL结构化健康数据
    ├─→ 本地原始报文暂存文件
    └─→ OSS压缩归档

浏览器前端
    ↓ HTTPS :443
Nginx
    ↓
FastAPI查询接口
    ↓
MySQL
```

TCP解析模块与FastAPI在同一台服务器时，写入接口仅监听本机地址，不对公网开放。

## 4. TCP解析模块提交的数据

TCP解析模块调用：

```text
POST /api/v1/health
Content-Type: application/json
X-Internal-Token: <内部密钥>
```

请求示例：

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

字段约定：

- `imei` 为设备唯一编号；
- `message_type=50` 表示TCP消息ID `0x32`；
- `collected_at` 必须使用UTC ISO 8601格式；
- 未采集到的健康项目传 `null`，不能自行填0；
- `raw_hex` 保存完整原始TCP帧的十六进制文本；
- JSON字段名称一旦确定，三方未经共同确认不得自行修改。

## 5. 校验规则

FastAPI接收数据后进行以下校验：

- IMEI必须为14至20位数字；
- 心率允许为空，有值时范围为20至250次/分钟；
- 血氧允许为空，有值时范围为0至100%；
- 体温和腕温允许为空，有值时范围为16.0至60.0摄氏度；
- 收缩压和舒张压允许为空，有值时范围为20至250mmHg；
- 步数允许为空，有值时不能为负数；
- `raw_hex` 必须为偶数长度的十六进制字符串；
- 采集时间不能明显晚于服务器当前时间，也不能早于允许接收的历史范围。

业务上异常但格式合法的数据仍可保存，并可在后续增加异常标记；本模块不把设备测量结果当作医疗诊断。

## 6. 去重设计

根据以下内容生成SHA-256摘要 `event_hash`：

```text
IMEI + 采集时间 + 报文类型 + 原始报文摘要
```

`health_records`建立 `(event_hash, collected_date)` 唯一索引。同一报文因设备重发、网络重试或接口重试再次到达时，不重复写入。

重复数据返回HTTP 200，并在响应中注明 `duplicate=true`，让TCP模块停止重试。

## 7. MySQL数据模型

### 7.1 devices

保存设备基础信息：

- `id`：内部主键；
- `imei`：唯一索引；
- `name`：设备或佩戴者显示名称；
- `model`：默认为B2315P；
- `enabled`：是否允许接收；
- `last_seen_at`：最后一次有效数据到达时间；
- `created_at`、`updated_at`。

### 7.2 health_records

保存前端查询所需的结构化健康数据：

- `id`；
- `collected_date`：采集日期，用于分区和唯一键；
- `event_hash`；
- `imei`；
- `message_type`；
- `collected_at`：UTC采集时间；
- `received_at`：服务器接收时间；
- `heart_rate`；
- `blood_oxygen`；
- `body_temperature`；
- `wrist_temperature`；
- `diastolic`；
- `systolic`；
- `steps`；
- `raw_archive_id`：对应的原始报文归档批次，可在归档完成后更新。

索引：

- 唯一索引 `(event_hash, collected_date)`；
- 查询索引 `(imei, collected_at)`；
- 按 `collected_date` 建立月度范围分区。

结构化健康数据保留365天。定时维护任务创建未来月份分区，并删除超过365天的旧分区。

### 7.3 ingestion_errors

只记录接收或处理失败，不为每次成功上传重复创建日志：

- `id`；
- `request_id`；
- `imei`，无法识别时允许为空；
- `error_code`；
- `error_message`；
- `payload_excerpt`；
- `created_at`。

这样可避免一年额外产生约1.05亿行成功日志。

### 7.4 raw_archives

记录OSS归档批次，而不是为每个报文保存一条OSS记录：

- `id`；
- `archive_date`；
- `imei`；
- `oss_key`；
- `record_count`；
- `compressed_bytes`；
- `sha256`；
- `status`：pending、uploaded或failed；
- `retry_count`；
- `created_at`、`uploaded_at`。

每天每台设备最多形成一个归档对象，约73,000个对象/年，远小于按报文建立1.05亿个对象。

## 8. 原始TCP报文归档

原始报文不逐条存入MySQL。FastAPI收到数据后，将以下内容追加到本地按日期和IMEI划分的JSONL文件：

```text
spool/2026/08/31/868488079852388.jsonl
```

每行包括事件摘要、采集时间、接收时间和原始十六进制报文。定时任务在文件关闭后执行：

1. 压缩为gzip；
2. 计算SHA-256；
3. 上传到OSS；
4. 创建或更新 `raw_archives`；
5. OSS确认成功后删除对应本地文件。

OSS对象路径：

```text
raw/2026/08/31/868488079852388.jsonl.gz
```

OSS生命周期设置为365天自动删除。MySQL数据库备份使用单独路径和单独生命周期，不能与原始报文混用。

## 9. FastAPI接口

### 9.1 写入接口

`POST /api/v1/health`

响应约定：

- `201 Created`：新数据保存成功；
- `200 OK`：重复数据，已忽略；
- `401 Unauthorized`：内部令牌不正确；
- `422 Unprocessable Entity`：字段格式或范围错误；
- `503 Service Unavailable`：MySQL暂时不可用，TCP模块必须保留数据并重试。

### 9.2 前端查询接口

- `GET /api/v1/devices`：设备列表、启用状态和最后上报时间；
- `GET /api/v1/health/latest?imei=...`：某设备最新健康数据；
- `GET /api/v1/health/history?imei=...&start=...&end=...&page=...&page_size=...`：历史数据；
- `GET /api/v1/health/summary?imei=...&date=...`：按天统计，可在第一版完成后增加。

历史查询必须分页，单次时间范围默认不超过31天，`page_size`最大1000，防止前端一次读取全年数据拖慢MySQL。

## 10. 一致性与故障处理

一次请求的处理顺序：

1. 验证内部令牌和JSON字段；
2. 计算 `event_hash`；
3. 将原始报文追加到本地暂存文件；
4. 使用MySQL事务写入 `health_records` 并更新 `devices.last_seen_at`；
5. 返回保存结果；
6. 独立定时任务压缩并上传OSS。

故障规则：

- 重复数据视为成功；
- MySQL失败时返回503，TCP模块负责持久化待重试数据；
- OSS失败不影响结构化健康数据入库，本地暂存文件不得删除；
- OSS任务根据 `raw_archives.status` 定时重试；
- 进程重启后扫描未上传文件和pending记录继续处理；
- 磁盘剩余空间低于20%时必须报警并暂停删除操作。

TCP解析模块必须实现发送失败的本地队列，否则仅靠FastAPI无法保证MySQL故障期间不丢数据。这是两个模块之间的必要责任边界。

## 11. 阿里云部署和安全

建议正式配置：

- 4核8GB ECS；
- 40GB系统盘；
- 300GB ESSD数据盘起步，MySQL和暂存目录放数据盘；
- 5Mbps及以上公网带宽；
- OSS按实际使用量计费；
- 每天数据库备份，保留7份日备份和4份周备份。

一年1.05亿条结构化记录的实际空间受字段、索引和InnoDB配置影响，部署后必须监控增长速度，在磁盘达到70%前扩容。若只配置100GB数据盘，应缩短MySQL在线保留期或提前扩容。

安全组：

- `22/TCP`：仅允许管理员固定IP；
- `80/443`：提供网页和HTTPS API；
- `9000/TCP`：手环TCP服务；
- `3306`：禁止公网开放；
- `8000`：禁止公网直接开放。

MySQL使用独立低权限账号；OSS密钥通过环境变量或实例RAM角色提供，不写入源代码；生产环境使用HTTPS和强随机内部令牌。

## 12. 测试与验收

### 12.1 独立开发测试

在真实TCP服务完成前，使用Python脚本或Postman模拟TCP解析模块发送JSON。

必须覆盖：

- 完整健康数据；
- 部分健康字段为null；
- IMEI、时间和数值范围错误；
- 同一数据连续提交两次；
- MySQL停止和恢复；
- OSS断开和恢复；
- FastAPI进程重启后继续归档；
- 按IMEI和时间范围分页查询。

### 12.2 压力测试

模拟200台设备在同一分钟集中上报，并额外测试每秒20至50个请求的短时突发。验收时确认：

- 无数据重复；
- 无连接池耗尽；
- 接口响应时间稳定；
- MySQL CPU、内存和磁盘延迟正常；
- 前端查询不会阻塞写入；
- 暂存文件和OSS数量符合预期。

### 12.3 三方联调顺序

1. 你先用模拟JSON完成FastAPI、MySQL和查询接口；
2. 前端同学使用你的查询接口开发页面；
3. TCP同学根据固定JSON格式调用写入接口；
4. 使用一台手表联调；
5. 连续运行至少24小时；
6. 再逐步扩大到200台。

## 13. 完成标准

数据库模块满足以下条件即视为完成：

- 合法健康数据能够写入MySQL；
- 重复提交不产生重复记录；
- 无效数据有明确错误响应；
- 原始报文能够按天压缩上传OSS并保留一年；
- 前端可以查询最新和历史健康数据；
- MySQL和OSS短暂故障后能够恢复；
- 数据库端口不暴露公网；
- 200台每分钟上报的模拟压力测试通过；
- 有部署说明、接口说明、建表迁移和测试记录。
