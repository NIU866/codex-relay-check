"""Targeted OpenAI-compatible API checks. Secrets are never included in reports."""

import json
import re
import ssl
import time
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class Report:
    title: str
    details: str
    elapsed_ms: int | None = None


HINTS = {
    400: "核对模型名和请求格式。部分中转只支持 Chat Completions，或需要服务商指定参数。",
    401: "认证未通过。核对 Base URL 与密钥是否来自同一服务，再检查密钥有效期。",
    403: "请求权限不足。查看密钥权限、模型访问权限与服务商限制。",
    404: "找不到这个地址。核对 Base URL 的路径和接口是否启用，尤其是 Responses。",
    405: "服务器不支持此请求方法。核对 API 协议与 Base URL。",
    429: "可能触发频率限制或额度不足。查看服务商后台的用量和余额。",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize(url, kind):
    clean = url.strip()
    if any(char.isspace() or ord(char) < 32 for char in clean) or "\\" in clean:
        raise ValueError("Base URL 包含空格或不支持的字符。")
    try:
        part = urlsplit(clean)
        host = (part.hostname or "").rstrip(".").lower()
        _ = part.port
    except ValueError as error:
        raise ValueError("Base URL 的地址或端口格式不正确。") from error
    if not host or part.username is not None or part.password is not None or part.query or part.fragment:
        raise ValueError("请输入带协议的 API 根地址，格式如 https://服务地址/v1。")
    if part.scheme != "https" and not (
        part.scheme == "http" and host in {"127.0.0.1", "::1", "localhost"}
    ):
        raise ValueError("远程接口请使用 HTTPS。HTTP 仅用于本机测试。")
    if kind == "relay" and host == "api.openai.com":
        raise ValueError("当前选择了中转站密钥，Base URL 却指向 OpenAI 官方。请更换为中转站地址。")
    if kind == "official" and host != "api.openai.com":
        raise ValueError("OpenAI 官方密钥请配合 https://api.openai.com/v1 使用。")
    path = part.path.rstrip("/") or "/v1"
    if path.endswith(("/models", "/responses", "/chat/completions")):
        raise ValueError("Base URL 填写接口根路径，例如 https://服务地址/v1。")
    return urlunsplit((part.scheme, part.netloc, path, "", ""))


def inspect_log(text, kind):
    status = re.search(r"\b(400|401|403|404|405|429|5[0-9]{2})\b", text)
    is_official = bool(re.search(r"https?://api\.openai\.com(?=[:/\s]|$)", text, re.I))
    mismatch = kind == "relay" and is_official
    if mismatch:
        return Report("中转站密钥与请求地址疑似混用",
                      "原日志中的请求发往 api.openai.com。若使用中转站密钥，请先把 Codex 的 Base URL 改为中转站提供的 API 地址，再单独检测 /responses。")
    if not status and "invalid_api_key" in text:
        return Report("日志包含 invalid_api_key", HINTS[401])
    if status:
        code = int(status.group())
        return Report(f"日志显示 HTTP {code}", HINTS.get(code, "服务器端错误。检查服务商状态或稍后在本机重试。"))
    return Report("未识别到常见 HTTP 状态", "请粘贴包含状态码或 invalid_api_key 的报错片段。")


def request_check(base, kind, key, model, operation):
    if operation not in {"models", "responses"}:
        raise ValueError("未知的检查方式。")
    url = normalize(base, kind) + "/" + operation
    if not re.fullmatch(r"[\x21-\x7e]{1,1024}", key):
        raise ValueError("请输入有效的 API 密钥，密钥内不能含空格。")
    if operation == "responses" and not model:
        raise ValueError("测试 Responses 前请填写确切模型名。")
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json",
               "User-Agent": "CodexRelayCheck/1.0"}
    payload = None
    if operation == "responses":
        headers["Content-Type"] = "application/json"
        payload = json.dumps({
            "model": model, "input": "Reply with OK.",
            "max_output_tokens": 32, "store": False,
        }).encode("utf-8")
    start = time.monotonic()
    elapsed = lambda: round(1000 * (time.monotonic() - start))
    try:
        with build_opener(NoRedirect()).open(Request(url, data=payload, headers=headers), timeout=12) as response:
            status = response.status
            body = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        if 300 <= status < 400:
            return Report(f"HTTP {status} · 服务器要求跳转", "请直接填写跳转后的正确 API 地址。密钥未转发到跳转地址。", elapsed())
        return Report(f"HTTP {status} · 请求失败",
                      HINTS.get(status, "服务返回错误。检查服务商状态和 API 路径。"), elapsed())
    except (TimeoutError, URLError, OSError, HTTPException, UnicodeError, ValueError) as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, ssl.SSLCertVerificationError):
            hint = "TLS 证书校验失败。核对域名与服务端证书。"
        elif isinstance(reason, TimeoutError):
            hint = "请求超时。检查网络、代理或该节点是否可用。"
        else:
            hint = "无法连接。核对域名、端口、网络连接或代理设置。"
        return Report("连接失败", hint, elapsed())

    if len(body) > 1024 * 1024:
        return Report(f"HTTP {status} · 响应体过大", "接口已连通。该响应超出 1 MB 检测上限。", elapsed())
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        data = None
    if not isinstance(data, dict) or data.get("error"):
        return Report(f"HTTP {status} · 响应格式异常", "检查返回的是 API JSON，部分地址会返回登录页或网关页面。", elapsed())

    if operation == "models":
        items = data.get("data")
        if not isinstance(items, list):
            return Report(f"HTTP {status} · 模型列表格式异常", "响应缺少标准的 data 模型列表。", elapsed())
        ids = {item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)}
        detail = f"服务返回 {len(ids)} 个模型。"
        if model:
            detail += "列表中找到了填写的模型。" if model in ids else "列表未包含填写的模型，请核对名称或账户权限。"
    elif data.get("object") == "response" or isinstance(data.get("output"), list):
        detail = "服务器返回 Responses 格式。路由与本次认证通过。"
        if data.get("status") == "incomplete":
            detail += "测试输出达到小额度上限。"
        elif data.get("status") in ("failed", "cancelled"):
            detail = "服务器识别了 Responses 请求，但报告生成失败或取消。请查看服务商后台。"
    else:
        return Report(f"HTTP {status} · 兼容格式待确认", "已收到 JSON，但响应未包含 Responses 的标准字段。", elapsed())
    return Report(f"HTTP {status} · API 已连通", detail, elapsed())
