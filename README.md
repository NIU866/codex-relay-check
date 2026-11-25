# Codex 中转站诊断器

[下载 Windows x64 便携版](https://github.com/NIU866/codex-relay-check/releases/latest)

解压后双击 CodexRelayCheck.exe。

- **连接检查**支持一次 GET /models 或 POST /responses 请求。填写服务商给出的 Base URL、所用密钥，任选需要检查的模型。
- **报错分析**在本地识别常见 HTTP 状态，并提示「中转站密钥搭配 api.openai.com」这种地址混用。
- 密钥仅在运行时用于明确填写的目的地。工具拒绝跟随 HTTP 跳转，报告不含密钥和原始响应。报错分析不发送网络请求。
- Responses 测试发送固定短句，设置 32 个输出 token 上限，可能消耗少量 API 额度。诊断定位 API 请求问题；旧对话能否继续仍取决于 Codex 和服务商的会话兼容性。

源码需要 Python 3.12 和标准库 Tkinter。运行 python relay_check.py。执行 python -m unittest -v 可使用本地模拟服务器测试，无需实际 API 密钥。
