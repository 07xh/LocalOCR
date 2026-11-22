# LocalOCR v0.2.0 · 本地 OCR 引擎、HTTP API 与标注工作台

这是一个**与原有私人仓库完全分离**的 OCR 项目。当前核心任务是识别用户有权处理的图片、支持其他程序通过 API 调用，以及为将来训练自有模型整理可审核的数据。它既不依赖，也不更改 `campus-toolkit/tk_tool` 代码。

## 已经实现

- **引擎**：Tesseract OCR（已进行真实图片识别），RapidOCR 3.x/ONNX（GitHub Actions Linux/Windows 真模型推理通过；Windows 图形化实机仍待验收）。
- **API**：只绑定本机 `127.0.0.1:18765` 的 FastAPI 服务，需要持久化随机 API Key；Base64 PNG/JPEG/WEBP/BMP/TIFF 输入。
- **数据集**：本地 SQLite + 原图转 PNG，重复图片去重、人工审核、版本冲突保护、train/val/test 数据集分组、原 JSONL ZIP 导出，并新增 PaddleOCR **文字检测**和**文字识别**训练数据 ZIP（仅人工审核数据，不改变原 API）。
- **标注界面**：内置本地页面，支持导入、预览、鼠标框选、OCR 建议、手动纠错、保存、审核。
- **测试**：原有 25 项 Python 单元/API 测试与真实 Tesseract OCR 此前通过；新增 PaddleOCR 格式/API 回归测试和 Linux/Windows RapidOCR **真实模型** CI 验收流程，最新 CI 已通过：单元/API 回归 51 passed、3 skipped，Linux 真模型 1 passed、1 skipped，Windows 真模型 2 passed。Windows 浏览器交互与实际部署仍需验收。

## Windows 便携 EXE（GitHub Actions 构建）

仓库新增 [Windows EXE CI](.github/workflows/windows-exe.yml)；[已通过验收的便携包](https://github.com/07xh/LocalOCR/actions/runs/45040980898/artifacts/14761518276)（需要登录 GitHub 下载，Actions 产物有保留期限），采用 PyInstaller 的 **onedir** 模式，把 LocalOCR、网页资源、RapidOCR 和 ONNX 模型打包成 `LocalOCR-Windows-x64-portable.zip`。只有 CI 中实际运行生成的 EXE 通过模型加载、合成图像识别和本地 Studio API 测试才会上载该文件为 Actions 构建产物（**不是 GitHub Release**）。

GitHub Actions 下载的外层 artifact ZIP 内可能还包含一个分发 ZIP，请逐层解压后，双击 `LocalOCR.exe` 可打开本地工作台。要显示 API Key，在解压目录打开终端执行 `LocalOCR.exe key`。不可只复制 EXE、删掉 `_internal` 目录；模型及 DLL 位于同一分发目录。训练功能仍需另外安装完整 PaddlePaddle/PaddleOCR 和本地预训练权重，**不包含在便携包内**。**在便携版训练面板中必须填写「训练环境 Python」**，例如 `D:\\PaddleEnv\\Scripts\\python.exe`，并确认这个 Python 已安装 PaddlePaddle。软件在启动训练前会尝试在该环境导入 PaddlePaddle，拒绝误用 `LocalOCR.exe` 自身启动训练。

注意：CI 通过只证明 Windows Runner 的安装/识别/启动工作流；用户电脑、杀毒软件和不同 Windows 版本仍需实机验收。

## 离线环境诊断

在工作台连接本机 API Key 后，点击「环境诊断」查看 SQLite、数据目录、工作台资源、已安装 OCR 后端与便携包中的 ONNX 数量，诊断响应**不包含 API Key 或绝对文件路径**。

命令行可执行 `LocalOCR.exe doctor`（源码模式为 `python -m localocr doctor`）进行快速自检；`LocalOCR.exe doctor --deep` 会额外用工具生成的英文图片实际执行一次本地 RapidOCR 推理。深度诊断是识别链路测试，**并不证明真实照片准确率，也不是已经物理断网的测试**。

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

网页工作台的「PaddleOCR 检测集」按钮或 `GET /v1/datasets/export/paddle-det` 可获取已审核标注的标准检测格式 ZIP；「PaddleOCR 识别集」或 `GET /v1/datasets/export/paddle-rec` 可获取按四点框矫正裁剪的文字识别训练集（`rec_gt_train.txt`、`rec_gt_val.txt`、`rec_gt_test.txt`）。训练/验证/测试划分需要用户在样本中明确设置，工具不会把未分配样本直接用于训练。

### 训练任务历史、模型登记与独立评估

训练工作台新增「查看历史任务」「查看已登记模型」「登记训练产物」「计算 CER / 整行正确率」。模型版本表只保存本地已完成训练产物的路径、哈希与来源，不会自动替换运行中的 RapidOCR。训练日志可显示观测到的轮次进度；服务重启后对无法确认的运行状态明确标记为 `unknown_after_restart`。

准确率评估要求 **test 集独立于训练/验证集**。使用另行生成的 `predictions.jsonl`，每行形如 `{"image":"rec/test/123.png","text":"识别文本"}`，与 `rec_gt_test.txt` 对照计算 CER 和精确匹配率；遗漏预测会计为错误，且不向 API 返回参考文字。这里只建立了可复现的评估入口，**还未跑出针对你实际图片的准确率报告**。

### 断点续训（可选）

训练面板现在允许填写「恢复既有训练」任务 ID，并选择 `latest` 或 `best_accuracy`。进入「查看历史任务」确认可用的 `resume_candidates`，再填入原任务的本机 PaddleOCR 目录、数据集和预训练权重。通过「检查配置」之后才启动新的训练任务，原产物不会被覆盖。仅当原任务已经结束、存在完整的模型/优化器/训练状态文件并且原始训练设置和训练/验证标签没有改变，才允许恢复。此功能已在 Linux CI 中使用官方 PaddleOCR 和合成文字数据验证了真实训练、断点续训及推理；Windows 端和实际个人数据仍待验收。

### 本地 PaddleOCR 模型微调入口

标注工作台底部新增「本地模型训练」折叠栏。操作步骤：

1. 在标注界面校对文字，人工审核并将样本**明确分配**至训练集与验证集；测试集保持独立。
2. 导出「PaddleOCR 识别集」ZIP，解压到本机数据目录。
3. 另行安装与设备兼容的 PaddlePaddle，并从官方 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 获取可信源码及 **PP-OCRv5 mobile-rec** 预训练权重（.pdparams）。不要使用不明来源权重。
4. 输入 PaddleOCR 源码目录、解压数据目录、权重路径；使用「检查配置」预检。预检检查至少 2 张训练文字裁剪、1 张验证文字裁剪、路径存在且无越界；不自动拿测试数据训练。
5. 「启动训练」将运行本机 `tools/train.py`（不经过 Shell），可以刷新日志、取消任务。成功完成后会在任务输出目录发现 `.pdparams` 模型文件；**不会自动把训练结果替换掉 RapidOCR 正在使用的模型**。

默认 CPU、10 轮、batch=4；小样本应先降低 batch size。模型训练执行效果依赖本机 PaddlePaddle、内存和配置，**现已在 Linux CI 使用合成数据真实跑通训练与续训，但不代表在实际图片上达到所需准确率**。这不是云端训练服务，也不会向外发送标注图片。

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

## 已审核测试集的本地 OCR 实测

在工作台中导入自己拥有或有权处理的图片，修改 OCR 建议并人工审核，再将保留图片设置为 `test`。打开训练面板，选择引擎并点击「评估测试集（首批）」；新的 `POST /v1/evaluation/reviewed-test` 不需要导出文件或手动准备 predictions.jsonl，即可真实调用本地 OCR，对文字框裁剪做 CER、精确匹配与耗时评估。支持分批测试，并且不把 OCR 建议当作真实标签。**仅评估识别，不评估图像检测；首批准确率并非全数据集准确率**。详细见 `docs/API.md`。

## 实际限制与后续

现阶段有**可运行的本地 OCR + 数据标注工作台源码**，并已由 Windows GitHub Actions **实际打包便携 EXE 并运行真实 OCR、网页及鉴权验收**，但尚非 GitHub Releases 正式发行版，也未完成用户电脑上的实机验收。已完成 Linux CI 合成数据的实际模型训练、续训与推理链路；Windows 图形界面实机、完全断网启动和真实图片识别准确率仍待验收。代码不包含任何第三方网站验证码在线验证/自动注册操作。

测试：`python -m pip install -e '.[dev,tesseract]'` 后运行 `python -m pytest -q`。参考项目及许可证核查入口见 [`docs/SOURCES.md`](docs/SOURCES.md)。
