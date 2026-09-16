# B2315P 前端发布手册

## 1. 推送 GitHub 分支

在本地 PowerShell 执行。不要在这一步执行 `git add .` 或提交主目录中的无关文件。

```powershell
Set-Location 'C:\Users\27838\Desktop\B2315P'
git push -u origin feature/full-platform
git push -u origin codex/frontend-v2-import
git push -u origin codex/frontend-v2-integration
```

分支用途：

- `feature/full-platform`：已跑通的后端与正式前端基线；
- `codex/frontend-v2-import`：同学交付的 V2 原稿，仅供审阅；
- `codex/frontend-v2-integration`：正式候选版本和兼容规则。

## 2. 上传正式候选构建包

当前候选包由 `codex/frontend-v2-integration` 构建，不是 V2 原稿构建包。PowerShell 中执行：

```powershell
$zip = 'C:\Users\27838\AppData\Local\Temp\b2315p-frontend-release-<timestamp>-69484a7.zip'
scp $zip root@8.152.103.37:/tmp/
```

## 3. 云服务器备份并部署

SSH 登录云服务器后执行。把 `<timestamp>` 换成压缩包文件名中的实际时间。

```bash
ZIP=/tmp/b2315p-frontend-release-<timestamp>-69484a7.zip
EXPECTED_SHA256=<本地Get-FileHash输出的SHA256>
echo "$EXPECTED_SHA256  $ZIP" | sha256sum -c -

STAMP=$(date +%Y%m%d%H%M%S)
STAGE=/tmp/b2315p-frontend-dist-$STAMP
mkdir -p "$STAGE"
unzip -q "$ZIP" -d "$STAGE"
test -s "$STAGE/index.html"
test -d "$STAGE/assets"

sudo install -d -m 700 /var/backups/b2315p/frontend
BACKUP=/var/backups/b2315p/frontend/frontend-dist-before-$STAMP.tar.gz
sudo tar -czf "$BACKUP" -C /var/www/b2315p/frontend dist
sudo chmod 600 "$BACKUP"

sudo mv /var/www/b2315p/frontend/dist \
  /var/www/b2315p/frontend/dist.previous-$STAMP
sudo mv "$STAGE" /var/www/b2315p/frontend/dist
sudo chown -R root:root /var/www/b2315p/frontend/dist
sudo find /var/www/b2315p/frontend/dist -type d -exec chmod 755 {} +
sudo find /var/www/b2315p/frontend/dist -type f -exec chmod 644 {} +

sudo nginx -t
sudo systemctl reload nginx
curl -fsS http://127.0.0.1/healthz
```

## 4. 浏览器验收

打开 `http://8.152.103.37/`，依次检查：

1. 未登录访问会进入登录页；
2. 管理员登录成功；
3. 设备列表和健康数据来自真实接口；
4. 定位、报警、睡眠和设备设置页面能打开；
5. 退出登录后再次访问受保护页面会回到登录页；
6. 浏览器开发者工具中没有持续的 `401`、`404` 或 `5xx`。

## 5. 失败回滚

如果验收失败，在云服务器执行：

```bash
STAMP=<本次发布时间>
test -n "$STAMP"
test -d "/var/www/b2315p/frontend/dist"
test -d "/var/www/b2315p/frontend/dist.previous-$STAMP"
test ! -e "/var/www/b2315p/frontend/dist.failed-$STAMP"
sudo mv /var/www/b2315p/frontend/dist /var/www/b2315p/frontend/dist.failed-$STAMP
sudo mv /var/www/b2315p/frontend/dist.previous-$STAMP \
  /var/www/b2315p/frontend/dist
sudo nginx -t
sudo systemctl reload nginx
```

回滚后再次打开网页并强制刷新。旧的压缩备份仍保存在 `/var/backups/b2315p/frontend/`。
