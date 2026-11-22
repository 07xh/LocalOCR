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
| `GET /v1/datasets/export?reviewed_only=true` | 原有 JSONL ZIP 导出 | 默认仅人工审核样本 |
| `GET /v1/datasets/export/paddle-det` | PPOCRLabel/PaddleOCR 检测标注 ZIP | 仅人工审核，按已有 split 输出 |
| `GET /v1/datasets/export/paddle-rec` | PaddleOCR 文字识别裁剪 ZIP | 仅已审核且明确分到 train/val/test 的样本 |
| `POST /v1/training/plan` | 在本机验证 PaddleOCR 训练配置，返回固定命令 | `paddle_repo`、`dataset_dir`、`pretrained_model`、`epochs`、`batch_size`、`use_gpu`；可选 `resume_run_id`、`resume_checkpoint` |
| `POST /v1/training/start` | 本地启动单个 PaddleOCR 识别微调进程 | 同上；需明确由用户触发 |
| `GET /v1/training/status` | 查询状态、退出码、最近日志及已生成权重文件 | 无 |
| `POST /v1/training/cancel` | 终止当前本地训练任务 | 无 |
| `GET /v1/training/history` | 查看已保存的训练任务记录，重启后无法确认状态的任务标为 unknown | `limit` 可选 |
| `POST /v1/evaluation/recognition` | 在明确保留的测试集计算 CER 与整行精确匹配率 | `dataset_dir`, `predictions_path` 本地绝对路径 |
| `POST /v1/evaluation/reviewed-test` | 用已安装本地引擎评测人工审核 test 组的文字区域 | `engine`, `limit` (1–20，默认 5), `offset` |
| `GET /v1/models` | 列出已登记的本地模型元数据和 SHA-256 | 无 |
| `POST /v1/models/register` | 仅登记已完成训练任务的本地 `.pdparams` 权重 | `run_id`, `filename` |


标注 `lines` 的每一项包含 `text`（1–1024 字符）和 `box`（4 个 `[x,y]` 原图坐标）。`split` 取 `train`、`val`、`test`、`unassigned`。编辑时必须提供读取到的 `revision`，过期时返回 `409`，防止覆盖其他窗口修改。

导出 ZIP 包含 `images/*.png`、`labels.jsonl` 和 `manifest.json`。这是 **LocalOCR 自有通用 JSONL**，并非直接可被 PaddleOCR 训练脚本读取的完整格式；正式训练适配器还没有实现。单次导出最多 150 张图片、输入图片总大小最多 128 MiB。

**PaddleOCR 检测标注导出**：新接口返回 `images/*.png`、`Label.txt`、`det/train.txt`、`det/val.txt`、`det/test.txt` 和 `manifest.json`。每条标签遵循 `相对图片路径\\t[{"transcription": "文本", "points": [[x,y], ...], "difficult": false}]` 的标准检测格式；ZIP 解压目录可作为 PaddleOCR 检测数据集 `data_dir`，按需指定检测训练/验证标签路径。未分配 split 的已审核样本保留在 `Label.txt`，不会被擅自放入训练集。未审核样本不会进入新接口的导出结果。此格式只包含**文字检测标注**。另有 `paddle-rec` 将审核过、分配过数据集的文字框透视矫正成独立 PNG，并以 PaddleOCR 的 `文件路径<TAB>文字` 格式生成 `rec_gt_{train,val,test}.txt`。训练 API 只负责本地进程，不自动下载、自动标注或自动部署模型；不保证本机已有 PaddlePaddle。

## 本地训练检查点恢复（准备功能）

训练计划与启动 API 支持可选 `resume_run_id`（此前本机的 32 位任务 ID）和 `resume_checkpoint`（`latest` 或 `best_accuracy`）。只有存在 `.pdparams`、`.pdopt`、`.states` 三件文件、此前任务已结束，并且 PaddleOCR 源码目录、预训练权重、设备、批量大小与 **train/val 标签 SHA-256** 一致时才允许恢复。PaddleOCR 使用 `Global.checkpoints` 恢复权重、优化器和轮次；不会把单个权重文件当作可恢复任务。新轮次写入**新的任务目录**，不覆盖旧检查点。

旧版本的训练记录若没有可靠保存训练配置，会被拒绝恢复；需要先执行一项带完整训练配置记录的新任务。这是为避免错误模型与数据混合。对于已完成的任务，目标训练总轮次必须大于此前设置的轮次。只通过 CI 模拟任务验证数据接口和恢复参数，**尚未实际跑过 PaddleOCR 的跨任务完整续训**。

## 独立识别评估协议

手动或使用可信本地工具生成 `predictions.jsonl`，每一行一个 JSON 对象，例如：

```jsonl
{"image":"rec/test/1234_0000.png","text":"识别出来的文字"}
```

使用 `POST /v1/evaluation/recognition` 提交本地解压数据集路径与 predictions.jsonl 文件路径。API 只读取 `rec_gt_test.txt`，拒绝训练集或验证集图片、不允许重复预测，将缺失预测按错误计入结果。报告包含样本数、遗漏数、字符错误率（CER）、整行精确匹配率和输入文件 SHA-256。**这是离线计分器，不运行训练模型，也不会自动证明模型性能。** 所有训练任务及模型路径均留在本机，登记不意味着已通过权重加载或推理验证。

## 错误码

- `400`：参数、图片、标注内容不合法；
- `401`：缺失或错误的 API Key；
- `404`：找不到样本；
- `409`：修订号过期；
- `422`：JSON 字段模型不匹配；
- `503`：OCR 后端不可用。

## 防护边界

固定监听 `127.0.0.1`，只接受本地图片内容，不支持远程 URL。配置域名为 `localhost`、`127.0.0.1`；无 CORS 跨域授权，API 需随机密钥；UI 使用无 CDN 的静态资源和 CSP 响应头。不要把本地服务端口通过隧道或代理对外开放。

## 直接评测现有 OCR 引擎（无需预测文件）

在「标注工作台」给自己拥有的图片标注文字，人工审核，并将它们明确划入 `test` 组。随后点击「评估测试集（首批）」。新的接口会在**本机**按标注框裁剪文字区域，使用所选已安装引擎推理，与人工审核真值比较。

```http
POST /v1/evaluation/reviewed-test
X-API-Key: <本机密钥>
Content-Type: application/json

{"engine":"auto","limit":5,"offset":0}
```

返回 `evaluated_samples` / `evaluated_regions` / `cer` / `exact_match_rate` / `inference_ms_mean` / `next_offset` / `has_more`。一次最多 40 个文字区域；超限则返回 400，可减少每批图片数量。**每批次指标不能直接冒充整个测试集指标**。结果只计算 **OCR 文字识别**，不包含检测、网页验证码验证或在线注册。原始人工标注、OCR 文本不会出现在评估响应中，只返回有误差的区域索引、长度和编辑距离，不会修改数据库、保存预测内容或启动训练。未安装引擎返回 503；没有已审核 `test` 样本返回 400。

## 批量测试集汇总与分组质量分析（后续增强）

`POST /v1/evaluation/reviewed-test` 保留原参数和指标，并新增 `dataset_fingerprint` 和 `quality`。后者包括 `empty_predictions`、`latency_ms_p50` / `latency_ms_p90`，以及 `by_reference_length` 三个区间（1–4、5–12、13+ 个 Unicode 字符）的区域数、完全匹配数、编辑错误数、参考字符数、匹配率和 CER。没有样本的区间，匹配率和 CER 返回 `null`，不能当作 100% 准确率。

标注工作台的「批量汇总（最多 150 张）」通过现有 API 顺序读取批次，并按**总编辑错误/总参考字符**、**总完全匹配数/总区域数**计算汇总，不对各批次百分比做简单平均。请求较大的批次超出单次 40 区域时会回退到单图评测；某一图超过 40 区域时明确报错，不跳过该图而伪称全量完成。点击「停止批量评估」会在当前请求结束后停止。超过单次 150 张上限、发生错误或人工取消时均标注为**部分报告**，不伪称全量完成。

服务端对每个分页结果计算已审核测试图片 ID/修订号的 SHA-256 指纹（不是模型权重哈希）。一张测试图片的标注、状态或数据集分组变化时，新的指纹会变化；页面检测到前后不一致会中止汇总。数据集在单次推理过程中变化时，服务器也拒绝返回旧标签结果。这是对一致性的检测，**不提供阻止其他进程修改数据的长期锁**。

注册的 `.pdparams` 是 PaddleOCR 训练检查点元数据，不等同于已转换可加载的 RapidOCR ONNX 权重。当前工作台的引擎选择只在已安装的 RapidOCR / Tesseract 之间选择，**不表示已完成自训练模型上线、实时切换或回滚**。
