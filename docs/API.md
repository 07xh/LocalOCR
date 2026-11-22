# LocalOCR HTTP API · v0.2.0

本地服务默认地址：`http://127.0.0.1:18765`。通过 `python -m localocr studio` 启动标注工作台，访问 `/studio`。默认不会访问外部 OCR 服务。

所有 `/v1/*` 端点需要请求头 `X-API-Key`；在本机运行 `python -m localocr key` 获取密钥。不要把密钥放在浏览器公共网页、Git 仓库或日志中。

## 文字识别

- `GET /health`：服务版本和存活状态。
- `GET /v1/engines`：已安装的识别后端（不代表模型已完成推理验收）。
- `POST /v1/ocr`：`{"image_base64":"...","engine":"auto"}`，返回文本、行坐标、置信度和耗时。

单图限制：二进制最多 8 MiB、像素最多 1200 万；PNG/JPEG/WEBP/BMP/TIFF。仅支持 Base64 内容或数据 URI，不接受图片 URL。

## 图片标注数据库

图片保存在用户配置目录的 `dataset/images/`；SQLite 元数据保存在 `dataset/samples.sqlite3`。导入时统一转为 RGB PNG，并去除原图 EXIF。`source` 为用户自行填写的来源描述（敏感文件名可自行清理）。

| 请求 | 作用 | 主要输入 |
|---|---|---|
| `GET /v1/samples?limit=50&offset=0` | 按时间分页读取样本 | `1 ≤ limit ≤ 100` |
| `POST /v1/samples` | 导入单张图片并按像素去重 | `image_base64`, `source` |
| `GET /v1/samples/{id}` | 查看标注及审核状态 | 无 |
| `GET /v1/samples/{id}/image` | 获取本地 PNG | 无 |
| `POST /v1/samples/{id}/suggest` | OCR 文字建议，不写入真值 | 可选 `engine_name=auto` |
| `PUT /v1/samples/{id}/annotations` | 覆盖人工标注；状态退回待审核 | `expected_revision`, `lines` |
| `PATCH /v1/samples/{id}` | 调整分组/来源/审核状态 | `expected_revision`, `status`, `split`, `source` |
| `DELETE /v1/samples/{id}?expected_revision=N` | 删除图片和标注 | 修订号 |
| `GET /v1/datasets/stats` | 总数、审核和分组统计 | 无 |
| `GET /v1/datasets/export?reviewed_only=true` | ZIP 导出 | 默认仅人工审核样本 |

标注 `lines` 的每一项包含 `text`（1–1024 字符）和 `box`（4 个 `[x,y]` 原图坐标）。`split` 取 `train`、`val`、`test`、`unassigned`。编辑时必须提供读取到的 `revision`，过期时返回 `409`，防止覆盖其他窗口修改。

导出 ZIP 包含 `images/*.png`、`labels.jsonl` 和 `manifest.json`。这是 **LocalOCR 自有通用 JSONL**，并非直接可被 PaddleOCR 训练脚本读取的完整格式；正式训练适配器还没有实现。单次导出最多 150 张图片、输入图片总大小最多 128 MiB。

## 错误码

- `400`：参数、图片、标注内容不合法；
- `401`：缺失或错误的 API Key；
- `404`：找不到样本；
- `409`：修订号过期；
- `422`：JSON 字段模型不匹配；
- `503`：OCR 后端不可用。

## 防护边界

固定监听 `127.0.0.1`，只接受本地图片内容，不支持远程 URL。配置域名为 `localhost`、`127.0.0.1`；无 CORS 跨域授权，API 需随机密钥；UI 使用无 CDN 的静态资源和 CSP 响应头。不要把本地服务端口通过隧道或代理对外开放。
