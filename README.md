# LocalOCR v0.2.0 · 本地 OCR 引擎、HTTP API 与标注工作台

这是一个**与原有私人仓库完全分离**的 OCR 项目。当前核心任务是识别用户有权处理的图片、支持其他程序通过 API 调用，以及为将来训练自有模型整理可审核的数据。它既不依赖，也不更改 `campus-toolkit/tk_tool` 代码。

## 已经实现

- **引擎**：Tesseract OCR（已进行真实图片识别），RapidOCR 3.x/ONNX 适配层（真实模型推理待验收）。
- **API**：只绑定本机 `127.0.0.1:18765` 的 FastAPI 服务，需要持久化随机 API Key；Base64 PNG/JPEG/WEBP/BMP/TIFF 输入。
- **数据集**：本地 SQLite + 原图转 PNG，重复图片去重、人工审核、版本冲突保护、train/val/test 数据集分组、原 JSONL ZIP 导出，并新增 PPOCRLabel/PaddleOCR **文字检测标注** ZIP（仅已审核数据，不改变原 API）。
- **标注界面**：内置本地页面，支持导入、预览、鼠标框选、OCR 建议、手动纠错、保存、审核。
- **测试**：原有 25 项 Python 单元/API 测试与真实 Tesseract OCR 此前通过；新增 PaddleOCR 格式/API 回归测试和 Linux/Windows RapidOCR **真实模型** CI 验收流程，新增检查通过情况以 PR 状态为准。Windows 浏览器交互与实际部署仍需验收。

## Windows 安装（推荐 Windows 10/11，Python 3.10+）

在解压后的项目根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1
.\scripts\start_windows.bat
```

脚本创建 `.venv`，安装依赖并启动本地工作台。默认浏览器页面 `http://127.0.0.1:18765/studio`。打开页面后需要 API Key，可从另一个 PowerShell 窗口执行：

```powershell
.\.venv\Scripts\python.exe -m localocr key
```

将 Key 粘贴到网页顶部连接栏即可。API Key 保存在 `%LOCALAPPDATA%\LocalOCR\auth.json`，数据集默认保存在 `%LOCALAPPDATA%\LocalOCR\dataset\`。网页只将 Key 存于当前标签页 `sessionStorage`，不会上传到外网或跟随源码打包。

**RapidOCR 模型：** 安装首次需要包源可达，模型文件可能需要额外下载。请在实际机器上完成首次初始化后再做断网启动验收。如果暂时无法安装 RapidOCR，可使用 Tesseract 后端：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[tesseract]"
```

Tesseract 是另一款需要单独安装的程序；还需将 `tesseract.exe` 放入 PATH 并准备相应语言包。Python 包单独安装不足以完成实际 OCR。

## 命令行

```bash
python -m localocr studio                  # API + 自动打开标注工作台
python -m localocr studio --no-browser     # API + 手动打开浏览器
python -m localocr serve                   # 仅启动 API
python -m localocr key                     # 显示本地 API Key
python -m localocr engines                 # 列出当前可检测的识别引擎
python -m localocr recognize samples/sample.png --engine auto
```

## API 示例（供其他本地程序调用）

```python
import base64, json, subprocess, sys
from pathlib import Path
from urllib.request import Request, urlopen

key = subprocess.check_output([sys.executable, '-m', 'localocr', 'key'], text=True).strip()
encoded = base64.b64encode(Path('samples/sample.png').read_bytes()).decode('ascii')
req = Request('http://127.0.0.1:18765/v1/ocr',
              data=json.dumps({'image_base64': encoded, 'engine': 'auto'}).encode(),
              headers={'X-API-Key': key, 'Content-Type': 'application/json'}, method='POST')
with urlopen(req, timeout=90) as response:
    print(json.load(response)['text'])
```

网页工作台的「PaddleOCR 检测集」按钮或 `GET /v1/datasets/export/paddle-det` 可获取已审核标注的标准检测格式 ZIP；训练/验证/测试划分需要用户在样本中明确设置，工具不会把未分配样本直接用于训练。

其他接口请查看 [`docs/API.md`](docs/API.md)。成功响应包含 `engine`, `text`, `lines`, `width`, `height`, `elapsed_ms`。OCR 的模型猜测**不会自动存为真值**，需要人工核对保存；只审核过的样本会进入默认 ZIP 导出。

## 项目结构

```text
LocalOCR/
├── localocr/
│   ├── api.py             # 鉴权 HTTP API / 数据集接口 / 内嵌网页
│   ├── cli.py             # 本地 CLI / 启动工作台
│   ├── engine.py          # RapidOCR/Tesseract 双后端
│   ├── dataset.py         # SQLite、图片保管、标注和审核、导出
│   ├── image_io.py        # 图片安全解码
│   ├── settings.py        # 用户配置和密钥
│   └── web/               # HTML / CSS / JavaScript 标注界面
├── scripts/              # Windows 安装与启动脚本
├── tests/                # 真实 OCR 和 API / 样本单测
├── samples/              # 无个人信息的演示图片
└── docs/                 # API、架构路线、开源来源
```

## 实际限制与后续

现阶段是**可运行的本地 OCR + 数据标注工作台源码**，**并非完整训练软件或已经发布的 EXE**。已添加 PaddleOCR 检测标注格式导出，仍未完成 RapidOCR 的模型实测验收、Windows UI 实机验收、文字识别（rec）训练集转换或模型微调。代码不包含任何第三方网站验证码在线验证/自动注册操作。

测试：`python -m pip install -e '.[dev,tesseract]'` 后运行 `python -m pytest -q`。参考项目及许可证核查入口见 [`docs/SOURCES.md`](docs/SOURCES.md)。
