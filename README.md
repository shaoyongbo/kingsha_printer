# RICOH IPP 打印门户

一个轻量的局域网打印页面：上传 PDF / 图片，选择彩色或黑白、A4 或 A3、单面或双面、是否缩放，直接通过标准 **IPP 协议**发送到打印机，并实时显示上传与打印进度、打印机和纸盘状态。

已在 **RICOH M C2001** 上验证（IPP 地址 `ipp://172.166.162.20:631/ipp/print`），无需安装打印机驱动。

## 功能

- 支持 PDF、JPG、JPEG、PNG，单文件最大 **200 MB**
- 彩色 / 黑白打印
- 纸张 **A4 / A3**（图片会自动转换为对应尺寸的 PDF）
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
pip install flask pillow pypdf
```

## 快速开始

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

## 使用说明

1. 拖拽或点击选择文件；
2. 选择彩色/黑白、份数、纸张、单面/双面、缩放方式；
3. 点击「发送打印」；
4. 按钮下方显示上传进度，提交成功后显示打印进度（页数 / 百分比）；任务完成后自动刷新打印机状态。

## API

### `GET /api/status`

返回打印机状态、纸张、纸盘、墨粉等信息。

### `POST /api/print`

`multipart/form-data` 表单：

| 字段 | 取值 | 默认 |
| --- | --- | --- |
| `file` | PDF / JPG / JPEG / PNG | 必填 |
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
- 进度通过 `Get-Jobs` 查询 `job-impressions-completed` / `job-media-sheets-completed`。部分打印机（包括 M C2001）不支持 `Get-Job-Attributes`，因此按「进行中 / 已完成」两个队列查找任务。
- 图片通过 Pillow 转换为适配所选纸张的 PDF；彩色/黑白由打印机的 `print-color-mode` 属性决定，而不是在本地做灰度转换。
- 打印机未上报计数时，进度条显示不定进度动画，任务结束即置为 100%。

## 目录结构

```text
.
├── app.py              # Flask 服务、IPP 客户端、图片转 PDF
├── templates/
│   └── index.html      # 单页打印界面（内联 CSS / JS）
└── .gitignore
```

## 注意事项

- 页面没有登录鉴权，请仅在可信局域网内使用，不要直接暴露到公网。
- 打印任务一旦提交无法从本页面取消，需要在打印机面板或 Web Image Monitor 中操作。
- 「原始大小」模式下，PDF 中超出版面范围的内容可能被裁切。
- 打印机休眠或网络抖动时状态可能短暂显示离线，页面会自动重试。
