# LocalOCR v0.2.0 · 验收记录

日期：2026-11-22

## 实际完成的验证

- `python -m pytest -q`：**25 项通过**（旧版 13 项 + 新版 12 项，含标注/样本协议与安全校验）。
- `node --check localocr/web/studio.js`：JavaScript 语法检查通过。
- Tesseract 本地文字 OCR：单测在本环境真实调用系统 `tesseract` 并识别图片中的 `LOCAL OCR 2026`。
- 真实 HTTP 子进程链路：`/health` → `/v1/ocr` → 图片导入 → OCR 建议 → 标注保存 → 审核 → ZIP 导出，全部通过；图像返回 `LocalOCR 2026`（当次行置信度约 0.93），未授权 API 请求返回 401。
- 浏览器工作台：HTML、CSS、JavaScript 均能由 FastAPI 返回，API 需 X-API-Key；后端测试覆盖导入、去重、保存、审核、导出、删改冲突和只读 OCR 建议。

## 未通过环境验收的部分

- **RapidOCR 真实模型推理**：环境中未安装 RapidOCR / ONNX Runtime；尝试安装时 DNS/包源连接失败。代码与官方 3.x 输出结构一致，但不能把“适配器”当成真实模型验收。
- **浏览器点击自动化**：环境提供 Chromium，但访问本机测试服务被 `ERR_BLOCKED_BY_ADMINISTRATOR` 阻断。这个结果不是应用自身的 HTTP 错误；故未完成可视化交互的浏览器实际测试。
- **Windows EXE**：尚未生成，Windows 实机运行与首次模型缓存均未验收。
- **真正模型训练**：尚未实现；当前只有人工标注、审核和结构化数据集导出。

## 安全与使用范围

- 本地 API 默认只监听回环地址，访问样本及 OCR 都需要 API Key。
- 图片不会发送到第三方 OCR 服务；本地样本保存在用户配置目录（应避免包含敏感信息的共享/同步目录）。
- 导出只有经过人工审核的图片（除非 API 显式传 `reviewed_only=false`）。
- 不提供第三方验证码批量验证、自动注册或绕过安全机制的功能。
