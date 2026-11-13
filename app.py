#!/usr/bin/env python3
"""局域网打印门户：上传 PDF / 图片，通过 IPP 提交到 RICOH M C2001。

打印机：172.166.162.20:631 /ipp/print，支持 PDF、彩色/黑白 (print-color-mode)。
"""

import io
import os
import struct
import time
import urllib.error
import urllib.request

from flask import Flask, jsonify, render_template, request
from PIL import Image, ImageOps

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

PRINTER_HOST = os.environ.get("PRINTER_HOST", "172.166.162.20")
PRINTER_PORT = int(os.environ.get("PRINTER_PORT", "631"))
PRINTER_PATH = os.environ.get("PRINTER_PATH", "/ipp/print")
PRINTER_URI = f"ipp://{PRINTER_HOST}:{PRINTER_PORT}{PRINTER_PATH}"
HTTP_URI = f"http://{PRINTER_HOST}:{PRINTER_PORT}{PRINTER_PATH}"

MAX_UPLOAD = 200 * 1024 * 1024  # 200 MB
ALLOWED_EXTS = {"pdf", "jpg", "jpeg", "png"}
PAPER_MEDIA = {"a4": "iso_a4_210x297mm", "a3": "iso_a3_297x420mm"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

# 任务元数据（总页数、份数等），用于前端展示打印进度
JOB_CACHE = {}

# ---------------------------------------------------------------- IPP 基础

# IPP 值标签
TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_OCTET = 0x30
TAG_TEXT = 0x41
TAG_NAME = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_MIME = 0x49

# IPP 状态码
STATUS_TEXT = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted-attributes",
    0x0002: "successful-ok-conflicting-attributes",
    0x0400: "client-error-bad-request",
    0x0401: "client-error-forbidden",
    0x0402: "client-error-not-authenticated",
    0x0403: "client-error-not-authorized",
    0x0404: "client-error-not-possible",
    0x0405: "client-error-timeout",
    0x0406: "client-error-not-found",
    0x0407: "client-error-gone",
    0x0408: "client-error-request-entity-too-large",
    0x0409: "client-error-request-value-too-long",
    0x040A: "client-error-document-format-not-supported",
    0x040B: "client-error-attributes-or-values-not-supported",
    0x040C: "client-error-uri-scheme-not-supported",
    0x040D: "client-error-charset-not-supported",
    0x040E: "client-error-conflicting-attributes",
    0x040F: "client-error-compression-not-supported",
    0x0410: "client-error-compression-error",
    0x0411: "client-error-document-format-error",
    0x0412: "client-error-document-access-error",
    0x0500: "server-error-internal-error",
    0x0501: "server-error-operation-not-supported",
    0x0502: "server-error-service-unavailable",
    0x0503: "server-error-version-not-supported",
    0x0504: "server-error-device-error",
    0x0505: "server-error-temporary-error",
    0x0506: "server-error-not-accepting-jobs",
    0x0507: "server-error-busy",
    0x0508: "server-error-job-canceled",
    0x0509: "server-error-multiple-document-jobs-not-supported",
}

ERROR_TEXT = {
    0x0406: "打印机找不到指定的任务。",
    0x0408: "文件太大，打印机拒绝接收。",
    0x040A: "打印机不支持该文件格式。",
    0x040B: "打印机不支持所选打印参数（例如颜色模式）。",
    0x0504: "打印机设备故障，请检查面板提示。",
    0x0505: "打印机临时错误，请稍后重试。",
    0x0506: "打印机当前不接受打印任务。",
    0x0507: "打印机忙，请稍后重试。",
}


def _attr(tag, name, value):
    n = name.encode("utf-8")
    if isinstance(value, bool):
        value = b"\x01" if value else b"\x00"
    elif isinstance(value, int):
        value = struct.pack(">i", value)
    elif isinstance(value, str):
        value = value.encode("utf-8")
    return (
        bytes([tag])
        + struct.pack(">H", len(n))
        + n
        + struct.pack(">H", len(value))
        + value
    )


def _decode_value(tag, raw):
    if tag in (TAG_INTEGER, TAG_ENUM):
        return struct.unpack(">i", raw)[0]
    if tag == TAG_BOOLEAN:
        return struct.unpack(">b", raw)[0]
    if tag == TAG_OCTET:
        return raw.hex()
    return raw.decode("utf-8", "replace")


def _parse_response(data):
    if len(data) < 8:
        raise ValueError("打印机返回的数据不完整")
    status = struct.unpack(">H", data[2:4])[0]
    result = {"status": status, "attributes": {}, "unsupported": []}
    i = 8
    group = 0
    last_name = None
    while i < len(data):
        tag = data[i]
        if tag == 0x03:  # end-of-attributes
            break
        if tag < 0x10:  # 分组标签
            group = tag
            last_name = None
            i += 1
            continue
        i += 1
        name_len = struct.unpack(">H", data[i:i + 2])[0]
        i += 2
        name = data[i:i + name_len].decode("utf-8", "replace")
        i += name_len
        if not name and last_name:
            name = last_name  # 同名属性的后续取值
        else:
            last_name = name
        value_len = struct.unpack(">H", data[i:i + 2])[0]
        i += 2
        raw = data[i:i + value_len]
        i += value_len
        if group == 0x05:  # unsupported-attributes
            result["unsupported"].append(name)
        else:
            result["attributes"].setdefault(name, []).append(
                _decode_value(tag, raw)
            )
    return result


def _ipp_request(operation, op_attrs, job_attrs=(), payload=b"", timeout=120):
    body = b"\x02\x00" + struct.pack(">H", operation) + struct.pack(">I", 1)
    body += b"\x01"
    for tag, name, value in op_attrs:
        body += _attr(tag, name, value)
    if job_attrs:
        body += b"\x02"
        for tag, name, value in job_attrs:
            body += _attr(tag, name, value)
    body += b"\x03" + payload

    req = urllib.request.Request(
        HTTP_URI, data=body, headers={"Content-Type": "application/ipp"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _parse_response(resp.read())


def _common_op_attrs(user="print-portal"):
    return [
        (TAG_CHARSET, "attributes-charset", "utf-8"),
        (TAG_LANGUAGE, "attributes-natural-language", "en"),
        (TAG_URI, "printer-uri", PRINTER_URI),
        (TAG_NAME, "requesting-user-name", user),
    ]


# ---------------------------------------------------------------- 业务逻辑

STATE_TEXT = {3: "就绪", 4: "处理中", 5: "已停止"}
JOB_STATE_TEXT = {
    3: "排队中",
    4: "已保留",
    5: "打印中",
    6: "打印暂停",
    7: "已取消",
    8: "已中止",
    9: "已完成",
}
REASON_TEXT = {
    "media-empty": "缺纸",
    "media-empty-warning": "纸盘缺纸",
    "media-empty-error": "缺纸",
    "media-jam": "卡纸",
    "media-jam-warning": "卡纸",
    "media-low": "纸张不足",
    "media-low-warning": "纸张不足",
    "cover-open": "盖板未关",
    "door-open": "门未关",
    "toner-empty": "墨粉用尽",
    "toner-low": "墨粉不足",
    "marker-supply-empty": "耗材用尽",
    "marker-supply-low": "耗材不足",
    "paused": "已暂停",
    "offline": "离线",
    "shutdown": "已关机",
    "stopping-error": "设备错误",
    "service-requested": "需要维修",
    "moving-to-paused": "正在暂停",
    "none": "无",
}


TRAY_STATUS_TEXT = {
    0: "就绪",
    1: "打开",
    2: "卡纸",
    3: "缺纸",
    4: "已满",
    5: "未知",
}

MEDIA_SIZE_NAMES = {
    (210, 297): "A4",
    (297, 420): "A3",
    (148, 210): "A5",
    (105, 148): "A6",
    (182, 257): "B5",
    (257, 364): "B4",
    (216, 279): "Letter",
    (216, 356): "Legal",
    (279, 432): "11×17",
}


def _tray_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_input_trays(values):
    """解析 PWG printer-input-tray：hex 编码的 key=value; 字符串。"""
    trays = []
    for raw in values:
        try:
            text = bytes.fromhex(raw).decode("utf-8", "replace")
        except (TypeError, ValueError):
            continue
        fields = {}
        for part in text.split(";"):
            if "=" in part:
                key, val = part.split("=", 1)
                fields[key.strip().lower()] = val.strip()
        name = fields.get("name", "")
        if not name or name.lower() == "auto":
            continue  # 过滤自动选择虚拟纸盘
        feed = _tray_int(fields.get("mediafeed"))
        xfeed = _tray_int(fields.get("mediaxfeed"))
        paper = None
        if feed and xfeed:
            mm = sorted((round(feed / 1000), round(xfeed / 1000)))
            paper = MEDIA_SIZE_NAMES.get(tuple(mm), f"{mm[0]}×{mm[1]}mm")
        level = _tray_int(fields.get("level"))
        capacity = _tray_int(fields.get("maxcapacity"))
        if level is not None and capacity and level > 100:
            level = round(level / capacity * 100)  # 部分机型按剩余张数上报
        status = _tray_int(fields.get("status")) or 0
        trays.append({
            "name": name,
            "paper": paper,
            "level": None if level is None else max(0, min(100, level)),
            "status": status,
            "statusText": TRAY_STATUS_TEXT.get(status, "未知"),
        })
    return trays


def get_printer_status():
    attrs = _common_op_attrs()
    for key in (
        "printer-name",
        "printer-info",
        "printer-state",
        "printer-state-reasons",
        "printer-state-message",
        "queued-job-count",
        "media-ready",
        "printer-input-tray",
        "marker-names",
        "marker-levels",
        "print-color-mode-supported",
    ):
        attrs.append((TAG_KEYWORD, "requested-attributes", key))
    last_exc = None
    for attempt in range(2):
        try:
            result = _ipp_request(0x000B, attrs, timeout=8)
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(1)  # 打印机休眠唤醒时首次请求可能超时，重试一次
    else:
        raise RuntimeError("连接打印机超时，请检查打印机电源和网络") from last_exc
    if result["status"] >= 0x0100:
        raise RuntimeError(
            ERROR_TEXT.get(
                result["status"],
                STATUS_TEXT.get(result["status"], f"打印机返回错误 0x{result['status']:04x}"),
            )
        )
    a = result["attributes"]
    state = a.get("printer-state", [0])[0]
    reasons = a.get("printer-state-reasons", [])
    names = a.get("marker-names", [])
    levels = a.get("marker-levels", [])
    supplies = [
        {"name": n, "level": levels[i] if i < len(levels) else None}
        for i, n in enumerate(names)
    ]
    return {
        "name": a.get("printer-name", ["打印机"])[0],
        "info": a.get("printer-info", [""])[0],
        "state": state,
        "stateText": STATE_TEXT.get(state, "未知"),
        "reasons": reasons,
        "reasonsText": [REASON_TEXT.get(r, r) for r in reasons],
        "message": a.get("printer-state-message", [""])[0],
        "queuedJobs": a.get("queued-job-count", [0])[0],
        "mediaReady": a.get("media-ready", []),
        "trays": parse_input_trays(a.get("printer-input-tray", [])),
        "supplies": supplies,
        "colorModes": a.get("print-color-mode-supported", []),
    }


def pdf_page_count(raw):
    if PdfReader is None:
        return None
    try:
        return len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # noqa: BLE001
        return None


JOB_ATTR_NAMES = (
    "job-id",
    "job-state",
    "job-state-reasons",
    "job-state-message",
    "job-impressions",
    "job-impressions-completed",
    "job-media-sheets-completed",
)


def _list_jobs(which):
    """该打印机不支持 Get-Job-Attributes，改用 Get-Jobs 按状态列出任务。"""
    attrs = _common_op_attrs()
    attrs.append((TAG_KEYWORD, "which-jobs", which))
    for key in JOB_ATTR_NAMES:
        attrs.append((TAG_KEYWORD, "requested-attributes", key))
    result = _ipp_request(0x000A, attrs, timeout=10)
    if result["status"] >= 0x0100:
        return []
    a = result["attributes"]

    def val(name, index, default=None):
        values = a.get(name) or []
        if index >= len(values) or values[index] in (None, ""):
            return default
        return values[index]

    return [
        {
            "jobId": job_id,
            "state": val("job-state", i, 0),
            "reasons": val("job-state-reasons", i, []),
            "message": val("job-state-message", i, ""),
            "impressions": val("job-impressions", i),
            "impressionsCompleted": val("job-impressions-completed", i),
            "mediaSheetsCompleted": val("job-media-sheets-completed", i),
        }
        for i, job_id in enumerate(a.get("job-id", []))
    ]


def get_job_status(job_id):
    job = next((j for j in _list_jobs("not-completed") if j["jobId"] == job_id), None)
    if job is None:
        job = next((j for j in _list_jobs("completed") if j["jobId"] == job_id), None)
    if job is None:
        raise LookupError("未找到该打印任务，可能已被打印机清除")

    state = job["state"]
    finished = state in (7, 8, 9)

    cached = JOB_CACHE.get(job_id, {})
    total_pages = cached.get("totalPages")
    # 打印机可能不返回 job-impressions-completed，退回使用已完成纸张数
    completed = job["impressionsCompleted"]
    if completed is None and job["mediaSheetsCompleted"] is not None:
        # 双面时 1 张纸对应 2 个页面
        completed = job["mediaSheetsCompleted"] * (
            2 if cached.get("sides") == "two-sided-long-edge" else 1
        )
    if completed is None:
        completed = 0

    percent = None
    if total_pages:
        percent = min(100, round(completed / total_pages * 100))
    if state == 9:  # 任务完成即视为 100%
        percent = 100

    submitted = cached.get("submittedAt")
    return {
        "jobId": job_id,
        "state": state,
        "stateText": JOB_STATE_TEXT.get(state, "未知"),
        "reasons": job["reasons"],
        "message": job["message"],
        "impressions": job["impressions"],
        "impressionsCompleted": job["impressionsCompleted"],
        "mediaSheetsCompleted": job["mediaSheetsCompleted"],
        "completedPages": completed,
        "totalPages": total_pages,
        "percent": percent,
        "elapsed": int(time.time() - submitted) if submitted else None,
        "finished": finished,
    }


def image_to_pdf(raw, paper="a4"):
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, "white")
        if img.mode in ("RGBA", "LA"):
            background.paste(img, mask=img.split()[-1])
        else:
            background.paste(img.convert("RGB"))
        img = background
    if img.mode == "L":
        img = img.convert("RGB")

    dpi = 200
    sheets = {"a4": (210, 297), "a3": (297, 420)}
    width_mm, height_mm = sheets.get(paper, sheets["a4"])
    short = int(min(width_mm, height_mm) / 25.4 * dpi)
    long = int(max(width_mm, height_mm) / 25.4 * dpi)
    margin = int(10 / 25.4 * dpi)
    portrait = img.height >= img.width
    page_w, page_h = (short, long) if portrait else (long, short)

    thumb = img.copy()
    thumb.thumbnail((page_w - 2 * margin, page_h - 2 * margin), Image.LANCZOS)
    page = Image.new("RGB", (page_w, page_h), "white")
    page.paste(thumb, ((page_w - thumb.width) // 2, (page_h - thumb.height) // 2))

    buf = io.BytesIO()
    page.save(buf, "PDF", resolution=dpi)
    return buf.getvalue()


def prepare_document(filename, raw, paper="a4"):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        if not raw.startswith(b"%PDF"):
            raise ValueError("文件内容不是有效的 PDF")
        return raw, "application/pdf"
    if ext in ("jpg", "jpeg", "png"):
        try:
            return image_to_pdf(raw, paper), "application/pdf"
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"图片解析失败：{exc}") from exc
    raise ValueError("仅支持 PDF、JPG、PNG 文件")


# ---------------------------------------------------------------- 路由

@app.route("/")
def index():
    return render_template(
        "index.html",
        printer_host=f"{PRINTER_HOST}:{PRINTER_PORT}",
    )


@app.get("/api/status")
def api_status():
    try:
        return jsonify({"ok": True, **get_printer_status()})
    except urllib.error.URLError as exc:
        return (
            jsonify({"ok": False, "error": f"无法连接打印机：{exc.reason}"}),
            502,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"读取打印机状态失败：{exc}"}), 502


@app.get("/api/jobs/<int:job_id>")
def api_job(job_id):
    try:
        return jsonify({"ok": True, **get_job_status(job_id)})
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except urllib.error.URLError as exc:
        return jsonify({"ok": False, "error": f"无法连接打印机：{exc.reason}"}), 502
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"查询任务失败：{exc}"}), 502


@app.post("/api/print")
def api_print():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "请选择要打印的文件"}), 400

    filename = os.path.basename(upload.filename).strip() or "document"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTS:
        return jsonify({"ok": False, "error": "仅支持 PDF、JPG、PNG 文件"}), 400

    color_mode = request.form.get("colorMode", "color")
    if color_mode not in ("color", "monochrome"):
        return jsonify({"ok": False, "error": "颜色模式无效"}), 400

    sides = request.form.get("sides", "one-sided")
    if sides not in ("one-sided", "two-sided-long-edge"):
        return jsonify({"ok": False, "error": "单双面参数无效"}), 400

    paper = request.form.get("paperSize", "a4")
    if paper not in PAPER_MEDIA:
        return jsonify({"ok": False, "error": "纸张参数无效"}), 400

    scaling = request.form.get("scaling", "fit")
    if scaling not in ("fit", "none"):
        return jsonify({"ok": False, "error": "缩放参数无效"}), 400

    try:
        copies = int(request.form.get("copies", "1"))
    except ValueError:
        copies = 1
    if copies < 1 or copies > 99:
        return jsonify({"ok": False, "error": "份数需在 1-99 之间"}), 400

    raw = upload.read()
    if not raw:
        return jsonify({"ok": False, "error": "文件为空"}), 400

    try:
        payload, mime = prepare_document(filename, raw, paper)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    op_attrs = _common_op_attrs() + [
        (TAG_NAME, "job-name", filename[:120]),
        (TAG_MIME, "document-format", mime),
    ]
    job_attrs = [
        (TAG_KEYWORD, "print-color-mode", color_mode),
        (TAG_INTEGER, "copies", copies),
        (TAG_KEYWORD, "media", PAPER_MEDIA[paper]),
        (TAG_KEYWORD, "sides", sides),
        (TAG_KEYWORD, "print-scaling", scaling),
    ]

    try:
        result = _ipp_request(0x0002, op_attrs, job_attrs, payload)
    except urllib.error.URLError as exc:
        return jsonify({"ok": False, "error": f"无法连接打印机：{exc.reason}"}), 502
    except TimeoutError:
        return jsonify({"ok": False, "error": "连接打印机超时"}), 504
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"提交打印任务失败：{exc}"}), 502

    status = result["status"]
    if status >= 0x0100:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": ERROR_TEXT.get(
                        status, STATUS_TEXT.get(status, f"打印失败（0x{status:04x}）")
                    ),
                    "status": STATUS_TEXT.get(status, hex(status)),
                }
            ),
            502,
        )

    job_id = result["attributes"].get("job-id", [None])[0]
    if job_id is not None:
        pages = pdf_page_count(payload)
        JOB_CACHE[job_id] = {
            "totalPages": pages * copies if pages else None,
            "copies": copies,
            "sides": sides,
            "paper": paper,
            "submittedAt": time.time(),
        }
        # 仅保留最近的 50 个任务，避免缓存无限增长
        for old_id in list(JOB_CACHE)[:-50]:
            JOB_CACHE.pop(old_id, None)

    return jsonify(
        {
            "ok": True,
            "jobId": job_id,
            "jobName": filename,
            "colorMode": color_mode,
            "sides": sides,
            "paperSize": paper,
            "scaling": scaling,
            "copies": copies,
            "totalPages": JOB_CACHE.get(job_id, {}).get("totalPages"),
            "status": STATUS_TEXT.get(status, "successful-ok"),
            "ignored": result["unsupported"],
        }
    )


@app.errorhandler(413)
def too_large(_):
    return jsonify({"ok": False, "error": "文件超过 200MB 限制"}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8090"))
    print(f"打印门户已启动：http://0.0.0.0:{port}  →  打印机 {PRINTER_HOST}:{PRINTER_PORT}")
    app.run(host="0.0.0.0", port=port, threaded=True)
