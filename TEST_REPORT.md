# LocalOCR v0.2.0 · 验收记录

日期：2026-11-22

## 实际完成的验证

- `python -m pytest -q`：**25 项通过**（旧版 13 项 + 新版 12 项，含标注/样本协议与安全校验）。
- `node --check localocr/web/studio.js`：JavaScript 语法检查通过。
- Tesseract 本地文字 OCR：单测在本环境真实调用系统 `tesseract` 并识别图片中的 `LOCAL OCR 2026`。
- 真实 HTTP 子进程链路：`/health` → `/v1/ocr` → 图片导入 → OCR 建议 → 标注保存 → 审核 → ZIP 导出，全部通过；图像返回 `LocalOCR 2026`（当次行置信度约 0.93），未授权 API 请求返回 401。
- 浏览器工作台：HTML、CSS、JavaScript 均能由 FastAPI 返回，API 需 X-API-Key；后端测试覆盖导入、去重、保存、审核、导出、删改冲突和只读 OCR 建议。

## PR #1 合并后 CI 追加验收（2026-11-22）

- CI run: https://github.com/07xh/LocalOCR/actions/runs/45035599010 ，全部三个 job 通过。
- Linux API / dataset 回归：**29 passed, 3 skipped**；JS 语法检查通过；检测数据集新导出格式、审核限定、API 鉴权及原 JSONL 导出兼容性测试已覆盖。
- Linux RapidOCR + ONNX Runtime **真实推理**：**1 passed, 1 skipped**（中文字体不可用，中文测试跳过）。
- Windows RapidOCR + ONNX Runtime **真实推理**：**2 passed**；实际载入模型并识别英文与中文合成图片，Windows 日志采用安全的 ASCII 转义显示中文。
- 本次成功只证明指定 CI 环境的真实推理流程可用，**不代表 Windows 图形化安装、完全断网运行、复杂真实图片准确率或模型训练已经验收**。

## PR #2 合并后 CI 追加验收（2026-11-22）

- CI: https://github.com/07xh/LocalOCR/actions/runs/45036464073 ，三个 job 全部通过。
- API、识别裁剪数据集、训练任务配置与进程生命周期回归：**38 passed, 3 skipped**，工作台 JavaScript 语法检查通过。
- Linux RapidOCR 真模型推理：**1 passed, 1 skipped**；Windows RapidOCR 真模型推理：**2 passed**。
- 本次对训练管理的测试使用受控模拟子进程，验证路径与权重预检、固定启动参数、日志与状态、取消等流程；**没有实际执行 PaddleOCR 权重微调或宣称生成了训练好的模型**。
- 文字识别数据集：已验证只导出已审核且明确分组的图片，支持四点框裁剪、中文标签、独立测试集和鉴权 API。

## PR #3 追加 CI 验收（2026-11-22）

- [GitHub Actions 运行记录](https://github.com/07xh/LocalOCR/actions/runs/45037746723)：3 个 job 全部成功。
- Linux API/数据集/训练/模型管理回归：**44 passed, 3 skipped**，工作台 JavaScript 语法检查通过。
- Linux RapidOCR 真模型推理：**1 passed, 1 skipped**；Windows RapidOCR 真模型推理：**2 passed**。
- 新增独立测试集 CER/整行正确率离线计分器、训练记录持久化与历史、模型元数据 SHA-256 登记；新增部分均完成单元/API 测试。
- **限制**：模型注册不验证其可被推理引擎加载；离线评估使用用户提供的预测 JSONL；尚未完成真实 PaddleOCR 模型微调、Windows 桌面端训练、模型切换与回滚验收。

## PR #4 本地检查点续训验收（2026-11-22）

- PR：https://github.com/07xh/LocalOCR/pull/4 （已合并）
- CI：https://github.com/07xh/LocalOCR/actions/runs/45039142174 ，全部 3 个 job 成功；API/数据集/训练管理回归 **51 passed, 3 skipped**。
- Linux RapidOCR 真模型推理和 Windows RapidOCR 真模型推理持续通过。
- 已测试本地断点续训参数构造、来源任务限制、`.pdparams/.pdopt/.states` 检查、标签哈希变更拒绝、已完成任务轮次保护、历史检查点候选及 API 鉴权。
- **仍未完成 PaddleOCR 真实模型分段训练再恢复**，因此不能宣称现有功能已实机验证到最终精度。

## 未完成的环境验收

- **当前容器环境**：曾因 DNS/包源问题无法直接安装 RapidOCR；现已由 GitHub Actions 的 Linux/Windows 真模型运行补足该项 CI 验证，当前容器本机环境仍未安装。
- **浏览器点击自动化**：环境提供 Chromium，但访问本机测试服务被 `ERR_BLOCKED_BY_ADMINISTRATOR` 阻断。这个结果不是应用自身的 HTTP 错误；故未完成可视化交互的浏览器实际测试。
- **Windows EXE**：尚未生成，Windows 实机运行与首次模型缓存均未验收。
- **真正模型训练**：已有本地 PaddleOCR 训练启动/取消/日志 API 与工作台入口，尚未在安装 PaddlePaddle 的真实训练环境验证完整微调，尚缺断点恢复和产物评估。

## 安全与使用范围

- 本地 API 默认只监听回环地址，访问样本及 OCR 都需要 API Key。
- 图片不会发送到第三方 OCR 服务；本地样本保存在用户配置目录（应避免包含敏感信息的共享/同步目录）。
- 导出只有经过人工审核的图片（除非 API 显式传 `reviewed_only=false`）。
- 不提供第三方验证码批量验证、自动注册或绕过安全机制的功能。
