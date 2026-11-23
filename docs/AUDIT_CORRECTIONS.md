# LocalOCR 审查修正及阶段门禁（2026-11-23）

基线：`main@4599e96`。此文是对《07xh/LocalOCR 仓库全面技术审查与演进蓝图》的逐项复核，不替代真实设备和模型准确率验收。

## 已过时的结论

- **`DatasetStore.delete()` 先删图片后提交事务**：当前基线源代码是 **先完成 SQLite 事务退出（提交），再删除 PNG**。原报告的 P0 问题已不成立，不能按其建议重复“修复”。
- **显式训练 Python 的预检必然阻塞事件循环**：`build_plan()` 确实同步执行外部 Python 的 `import paddle`（最长 20 秒），但目前 FastAPI `/v1/training/plan` 和 `/v1/training/start` 是同步路由，框架会把同步路由交给线程池。主要影响是占用工作线程/请求响应时延，而非证明会阻塞整个事件循环。可后续针对重复预检做缓存和并发限制。

## 真实存在的缺口

- `OCRService` 仍以默认 `RapidOCR()` 初始化，尚不能选择已微调模型。
- `ModelRegistry` 仍是 `registered_unverified` 元数据登记；没有模型转换、独立质量门禁、启动确认或回滚。
- `live_evaluation.py` 的 `MAX_EVALUATION_REGIONS=40` 是整个单批请求的硬上限：单张多区域图也可能失败。
- 尚无个人 Windows 10/11 桌面浏览器交互、断网启动与真实图片准确率验收。CI Windows Runner 通过不能等同于本机验收。
- 2026-11-23 核对 `main@4599e96` 时，仓库尚无 GitHub Release。

## 本分支改动

- 修复模型注册表损坏 JSON 的错误包装和 OCR 后端异常归一化。
- 为新增图片提供独占创建并清理失败插入产生的孤儿文件；不能确认 SQLite 提交状态时优先保留文件，避免误删。
- 深度诊断提供 Pillow 内置字体回退。
- Studio 训练运行期间每 5 秒刷新状态；后台标签页暂停轮询。
- Windows CI 在成功烟测后输出 ZIP 与 SHA-256，并且仅当仓库发布语义版本 Tag 时创建**预发布版**（prerelease）。不自动生成 Tag、不宣称个人设备验收完成。

## Windows 实机验收清单（用户的真实 Windows 设备）

1. 从 GitHub Actions Artifact 下载 ZIP，检查 SHA-256，然后完整解压（保留 `_internal`）。
2. 在 Windows 10/11 中完全断网、从干净目录打开 `LocalOCR.exe`，执行 `doctor --deep`。
3. 在 Chrome/Edge 的 `http://127.0.0.1:18765/studio` 输入本地 API Key，验证图片导入、标注修改、保存/审核/导出、刷新状态。
4. 报告 Windows 版本、运行模式、错误码、独立验证截图；不包含本地 Key、用户图片或敏感文件路径。
5. 完成以上实机记录及 Tag CI 成功后，才考虑将预发布版提升为稳定 Release。

## 模型闭环必过门禁

见 [MODEL_DEPLOYMENT.md](MODEL_DEPLOYMENT.md)。任何 `.pdparams` 或 `.onnx` 文件在未经过兼容性、独立测试集精度、可逆切换与回滚验收前，仍只能登记为未验证产物。
