# 技术参考和开源许可证审查（2026-11-22）

本项目为原创适配层与 API；**未复制下列仓库的源文件、模型权重或图形素材**。开源项目的代码/模型许可证与再分发规则仍应在打包时复核。

| 项目/社区 | 公开资料 | 借鉴方向 | 选择 |
|---|---|---|---|
| RapidOCR（RapidAI） | https://github.com/RapidAI/RapidOCR ; https://rapidai.github.io/RapidOCRDocs/main/quickstart/ | ONNX 本地推理、多语言、结构化 `boxes/txts/scores` API | **主引擎**，后续验收模型冷/热启动 |
| Umi-OCR（hiroi-sora） | https://github.com/hiroi-sora/Umi-OCR | OCR 引擎与 UI / 任务管理分离、批量处理、后台 API 控制器 | **架构参考**，不直接移植 UI |
| PaddleOCR（PaddlePaddle） | https://github.com/PaddlePaddle/PaddleOCR | 高精度多语言 OCR、未来数据训练框架 | **后续训练后端候选** |
| PPOCRLabel（官方文档） | https://paddlepaddle.github.io/PaddleX/latest/data_annotations/ocr_modules/text_detection_recognition.html | 四点框标注、训练/验证/测试集导出 | **下一阶段标注界面参考** |
| Tesseract | https://github.com/tesseract-ocr/tesseract | 稳定 CLI OCR、识别对照基线 | **可选后备** |
| EasyOCR | https://github.com/JaidedAI/EasyOCR | 多语言模型及训练流程 | **备选，不做首发强依赖** |
| Label Studio | https://github.com/HumanSignal/label-studio | 标注审核、任务与数据集管理 | **交互设计参考** |

## 吾爱破解 / 小众软件社区

- 吾爱破解论坛有关 Umi-OCR、离线 OCR 引擎插件、PP-OCRv6 嵌入部署的帖子可作为 **Windows 实际使用需求的线索**。示例：社区帖子链接 https://www.52pojie.cn/thread-2114198-1-1.html （由 [Umi-OCR GitHub issue #1070](https://github.com/hiroi-sora/Umi-OCR/issues/1070) 提及）。
- 其他讨论线索：离线 OCR DLL https://www.52pojie.cn/thread-2090283-1-1.html （来自社区更新摘要）；Umi-OCR 使用反馈、离线识别与 Windows 便携部署。
- **证据限制**：本次搜索无法打开 52pojie 论坛原帖，未检查其实际源码、编译方法、版本和许可证。因此不从这些帖子复制二进制或推断其质量；只把离线、便携、清晰错误提示和可插拔引擎作为产品需求。
- 小众软件论坛《天若 OCR 开源版》讨论：https://meta.appinn.net/t/topic/74278 ，可用于 UI 体验和 Windows 兼容性需求的进一步研究。

## 许可证注意

RapidOCR、PaddleOCR、Tesseract、EasyOCR 等仓库声称采用 Apache-2.0 许可；实际打包时仍需保留适用的版权告知，尤其是预训练模型权重的来源、模型许可证和 NOTICE 文件。部分社区发布的 exe 未提供可审计源码，不纳入原样集成。
