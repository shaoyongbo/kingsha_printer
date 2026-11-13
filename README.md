# RICOH IPP 打印门户

一个轻量的局域网打印页面：上传 PDF、Word、HTML 或图片，选择彩色或黑白、A4 或 A3、单面或双面、是否缩放，直接通过标准 **IPP 协议**发送到打印机，并实时显示上传与打印进度、打印机和纸盘状态。

已在 **RICOH M C2001** 上验证（IPP 地址 `ipp://172.166.162.20:631/ipp/print`），无需安装打印机驱动。

## 功能

- 支持 PDF、Word（.docx）、HTML、JPG、JPEG、PNG，单文件最大 **200 MB**
- Word 和 HTML 在服务端自动转换为 PDF 后打印（含中文字体）
- 彩色 / 黑白打印
- 纸张 **A4 / A3**（图片、Word、HTML 会按所选纸张转换为 PDF）
- **单面 / 双面**（长边翻转）
- **缩放**：适应纸张 / 原始大小（原始大小仅对 PDF 生效，图片仍会适配页面）
- 份数 1–99
- 上传进度条（大文件也可看到传输百分比）
- 打印进度：百分比、已完成页数 / 总页数、任务状态、已用时
- 打印机状态：就绪状态、队列任务数、可用纸张、各纸盘余量与缺纸提醒、四色墨粉余量
- 状态每 30 秒自动刷新；离线时每 10 秒自动重试

## 环境要求

- Python 3.9+
- 可访问打印机的 IPP 端口（默认 631）

依赖：

```bash
pip install flask pillow pypdf mammoth xhtml2pdf
```

中文转换需要字体文件 `assets/wqy-microhei.ttc`（已随仓库提供）。

## 快速开始

一键启动（首次会自动安装依赖）：

```bash
./start.sh
```

或手动启动：

```bash
# 可选：指定打印机地址
export PRINTER_HOST=172.166.162.20

python3 app.py
```

浏览器打开 `http://<运行机器的IP>:8090/`。

若 8090 被占用，可通过环境变量修改：

```bash
PORT=9000 python3 app.py
```

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PRINTER_HOST` | `172.166.162.20` | 打印机 IP |
| `PRINTER_PORT` | `631` | IPP 端口 |
| `PRINTER_PATH` | `/ipp/print` | IPP 资源路径 |
| `PORT` | `8090` | Web 服务监听端口 |

监听地址固定为 `0.0.0.0`，便于局域网内其他设备访问。

## 页面使用方法

### 1. 打开页面

浏览器访问 `http://<运行机器IP>:8090/`（当前部署示例：`http://172.166.164.70:8090/`）。
页面右上角的状态标签显示打印机当前状态：就绪 / 打印中 / 已停止 / 离线。

### 2. 查看打印机状态

顶部「打印机状态」卡片显示：

- 状态徽标与状态信息（如 `Idle. · 纸盘 2、手送台 缺纸`）
- 队列任务数与可用纸张（如 A4）
- 各纸盘的纸张尺寸、余量与状态（纸盘 1 / 纸盘 2 / 手送台）
- 黑、青、品红、黄四色墨粉余量

状态每 30 秒自动刷新，点右上角刷新按钮可立即更新；离线时每 10 秒自动重试。

### 3. 选择文件

将 PDF / Word（.docx）/ HTML / JPG / JPEG / PNG 拖入上传区，或点击上传区选择文件，单文件最大 **200 MB**。
选中后显示文件名和大小，可点「移除」重新选择。Word 和 HTML 会在服务端自动转换为 PDF，无需本地安装 Office。

### 4. 设置打印参数

| 设置 | 可选项 | 说明 |
| --- | --- | --- |
| 颜色 | 彩色 / 黑白 | 由打印机 `print-color-mode` 属性控制 |
| 份数 | 1–99 | 可用 `-` / `+` 调整 |
| 纸张 | A4 / A3 | 图片、Word、HTML 会按所选纸张转换为 PDF |
| 面数 | 单面 / 双面 | 双面为长边翻转 |
| 缩放 | 适应纸张 / 原始大小 | 原始大小仅对 PDF 生效，超出部分可能被裁切 |

选择 A3 时会提示确认纸盘已装入 A3 纸张。

### 5. 发送并查看进度

点击「发送打印」后：

1. 按钮下方出现上传进度条和百分比（大文件传输时尤其有用）；
2. 上传完成后显示打印进度：百分比、已完成页数 / 总页数、当前状态和已用时；
3. 若打印机未上报页数，进度条显示不定进度动画，任务结束即置为 100%；
4. 打印完成后显示「打印完成」，并自动刷新打印机状态。

提交后请保持页面打开，否则将无法继续查看进度（打印任务本身会在打印机队列中继续执行）。

### 6. 提示信息

- 琥珀色提示：纸盘缺纸，按提示补充；其他纸盘有纸时仍可正常打印。
- 红色提示：文件过大、格式不支持或网络/打印机异常，按提示处理后重试。
- 打印机休眠或网络抖动时可能短暂显示离线，页面会自动恢复。

## API

### `GET /api/status`

返回打印机状态、纸张、纸盘、墨粉等信息。

### `POST /api/print`

`multipart/form-data` 表单：

| 字段 | 取值 | 默认 |
| --- | --- | --- |
| `file` | PDF / DOCX / HTML / JPG / JPEG / PNG | 必填 |
| `colorMode` | `color` / `monochrome` | `color` |
| `copies` | 1–99 | `1` |
| `sides` | `one-sided` / `two-sided-long-edge` | `one-sided` |
| `paperSize` | `a4` / `a3` | `a4` |
| `scaling` | `fit` / `none` | `fit` |

成功返回任务 ID、文件名及各选项，例如：

```json
{
  "ok": true,
  "jobId": 285,
  "jobName": "...",
  "colorMode": "color",
  "sides": "one-sided",
  "paperSize": "a4",
  "scaling": "fit",
  "copies": 1,
  "totalPages": 1
}
```

### `GET /api/jobs/<jobId>`

返回打印进度：

```json
{
  "ok": true,
  "jobId": 285,
  "state": 5,
  "stateText": "打印中",
  "completedPages": 1,
  "totalPages": 2,
  "percent": 50,
  "elapsed": 4,
  "finished": false
}
```

## 实现说明

- 后端直接用 Python 手写 IPP 报文，通过 `Print-Job` 提交任务，不依赖 CUPS 或厂商驱动。
- 总页数由 `pypdf` 读取 PDF（图片转成的 PDF 固定为 1 页）乘以份数得到。
- Word 转换使用 `mammoth` 提取正文、表格和图片；HTML 与转换后的 Word 内容由 `xhtml2pdf` 渲染为 PDF，并嵌入 `assets/wqy-microhei.ttc` 中文字体。
- HTML 中的脚本、iframe、外链样式会被移除；文档转换仅允许读取 `assets` 目录和公网图片，避免访问内网或本地文件。
- 进度通过 `Get-Jobs` 查询 `job-impressions-completed` / `job-media-sheets-completed`。部分打印机（包括 M C2001）不支持 `Get-Job-Attributes`，因此按「进行中 / 已完成」两个队列查找任务。
- 图片通过 Pillow 转换为适配所选纸张的 PDF；彩色/黑白由打印机的 `print-color-mode` 属性决定，而不是在本地做灰度转换。
- 打印机未上报计数时，进度条显示不定进度动画，任务结束即置为 100%。

## 目录结构

```text
.
├── app.py              # Flask 服务、IPP 客户端、文档转换
├── templates/
│   └── index.html      # 单页打印界面（内联 CSS / JS）
├── assets/
│   └── wqy-microhei.ttc # 文档转换使用的中文字体
├── start.sh            # 一键启动脚本
└── .gitignore
```

## 注意事项

- 页面没有登录鉴权，请仅在可信局域网内使用，不要直接暴露到公网。
- 打印任务一旦提交无法从本页面取消，需要在打印机面板或 Web Image Monitor 中操作。
- 「原始大小」模式下，PDF 中超出版面范围的内容可能被裁切。
- 旧版 `.doc` 不支持，请先另存为 `.docx`。
- Word / HTML 转换以正文、表格和图片为主，复杂排版（分栏、页眉页脚、文本框）可能与 Word 中看到的效果存在差异；HTML 中的外链图片需要能通过公网访问。
- 打印机休眠或网络抖动时状态可能短暂显示离线，页面会自动重试。
