# PDF Watermark Remover

一个基于 `PyMuPDF` 和 `tkinter` 的桌面图形化工具，用于为固定位置水印生成坐标，并批量去除 PDF 中重复出现的导出水印。

本项目特别适合这类场景：

- PDF 来自扫描/导出工具，水印总是出现在固定位置
- 希望先在界面中框选一次区域，再批量处理整批文件
- 需要导出坐标 JSON，后续复用到自己的 `PyMuPDF` 脚本中
- 希望直接打包为单文件程序给其他人使用

当前已支持处理类似“夸克扫描王”这类固定页眉、页脚或角落位置的导出水印。

## 功能特性

- 图形化框选 PDF 水印区域
- 自动将屏幕选区换算为 PDF 坐标
- 支持多块水印区域
- 支持导入 / 导出 JSON 坐标配置
- 支持单文件或整个目录批量处理
- 支持打开输出目录
- 支持两种处理模式
- `cover`：使用白色矩形覆盖，适合视觉去水印
- `redact`：真正删除矩形区域内容，适合明确知道区域内只有水印的情况
- 支持打包为单文件 Windows 可执行程序

## 适用范围

推荐用于以下类型的 PDF：

- 夸克扫描王等扫描工具导出的固定位置水印
- 每页水印位置一致或基本一致的 PDF
- 页尺寸相同，或可以通过归一化坐标适配的 PDF

不太适合以下情况：

- 每页水印位置都不同
- 水印与正文高度重叠，无法安全框选
- 水印不是位于固定区域，而是满页平铺、旋转、透明叠加

## 工作流程

1. 打开一份示例 PDF。
2. 在预览图上拖拽框选水印区域。
3. 自动生成 PDF 坐标与归一化坐标。
4. 导出 JSON 配置，或直接批量处理 PDF。
5. 在输出目录中查看处理结果。

## 安装

推荐先创建虚拟环境：

```bash
python -m venv .venv
```

然后按终端类型激活：

```bash
# PowerShell
.\.venv\Scripts\Activate.ps1

# CMD
.venv\Scripts\activate.bat

# Git Bash
source .venv/Scripts/activate
```

安装运行依赖：

```bash
pip install -r requirements.txt
```

## 启动

激活虚拟环境后：

```bash
python app.py
```

如果不激活虚拟环境，也可以直接运行：

```bash
# PowerShell / CMD
.\.venv\Scripts\python.exe app.py

# Git Bash
./.venv/Scripts/python.exe app.py
```

说明：

- Git Bash 中请优先使用 `/`，不要把 Windows 路径写成 `.venv\Scripts\python app.py`
- 在 Git Bash 中，反斜杠 `\` 会被当成转义字符，导致命令解析错误

## 使用说明

1. 点击“打开 PDF”加载一份示例文件。
2. 在左侧预览区域用鼠标拖拽，框选水印位置。
3. 在右侧查看区域列表和 JSON 预览。
4. 如需复用规则，可导出 JSON。
5. 设置批量输入路径、输出目录和处理模式。
6. 点击“开始批量去水印”。
7. 点击“打开目录”查看生成结果。

## 坐标配置格式

程序会生成类似如下的 JSON：

```json
{
  "version": 1,
  "sample_pdf": "sample.pdf",
  "sample_page_index": 0,
  "mode": "cover",
  "regions": [
    {
      "label": "区域 1",
      "points": {
        "x0": 60.5,
        "y0": 72.0,
        "x1": 180.5,
        "y1": 110.0
      },
      "page_size": {
        "width": 595.0,
        "height": 842.0
      },
      "normalized": {
        "x0": 0.101681,
        "y0": 0.085511,
        "x1": 0.303361,
        "y1": 0.130641
      }
    }
  ]
}
```

字段说明：

- `points`：原始 PDF 坐标
- `page_size`：标注时样本页面的宽高
- `normalized`：归一化坐标，适合跨页面尺寸复用

## 单文件打包

如果你希望把项目打包成“拿到就能用”的单文件程序，请先安装打包依赖：

```bash
pip install -r requirements-build.txt
```

执行打包：

```bash
python build_single_file.py
```

如果未激活虚拟环境，也可以这样执行：

```bash
# PowerShell / CMD
.\.venv\Scripts\python.exe build_single_file.py

# Git Bash
./.venv/Scripts/python.exe build_single_file.py
```

打包完成后，生成文件位于：

```text
dist/PDFWatermarkRemover.exe
```

Windows 用户拿到该 `.exe` 后，无需额外安装 Python、PyMuPDF 或 Pillow。

## 项目结构

```text
.
├─ app.py
├─ build_single_file.py
├─ requirements.txt
├─ requirements-build.txt
└─ pdf_watermark_remover/
   ├─ __init__.py
   ├─ gui.py
   └─ processor.py
```

文件说明：

- `app.py`：程序入口
- `build_single_file.py`：单文件打包脚本
- `pdf_watermark_remover/gui.py`：图形界面逻辑
- `pdf_watermark_remover/processor.py`：坐标模型与批量处理逻辑

## 技术栈

- `PyMuPDF`
- `tkinter`
- `Pillow`
- `PyInstaller`

## 已知限制

- 本项目主要面向固定位置水印，不包含 OCR、图像识别或自动定位逻辑
- `redact` 模式会删除选区内全部内容，不会只识别“水印对象”
- 如果水印压在正文上，去除水印的同时可能损伤正文内容
- 对于复杂透明水印、旋转斜铺水印、整页纹理水印，本项目不保证处理效果

## 合规说明

请仅用于处理你有权编辑、导出或清理的文档。

你应确保自己的使用行为符合当地法律法规、平台协议、版权约束以及文档所属方的授权要求。本项目不鼓励将其用于未获授权的内容处理、版权规避或其他不合规用途。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进以下方向：

- 更丰富的批处理选项
- 坐标模板管理
- 更好的多页预览体验
- 更完善的打包与发布流程

## License

本项目基于 [MIT License](./LICENSE) 开源。
