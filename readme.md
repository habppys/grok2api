# Grok2API

基于 **FastAPI** 重构的 Grok2API，全面适配最新 Web 调用格式，支持流式对话、图像生成、图像编辑、联网搜索、深度思考，号池并发与自动负载均衡一体化。

## 使用说明

### 调用次数与配额

- **普通账号（Basic）**：免费使用 **80 次 / 20 小时**
- **Super 账号**：配额待定（作者未测）
- 系统自动负载均衡各账号调用次数。

### 图像生成功能

- 在对话内容中输入如“给我画一个月亮”自动触发图片生成
- 每次以 Markdown 格式返回两张图片（直接使用 Grok 服务器 URL）
- 图片 URL 格式: https://assets.grok.com/...

### 普通文本对话

标准的 OpenAI 兼容接口，支持流式和非流式响应：

```bash
# 非流式响应（直接返回完整结果）
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "grok-4-fast",
    "messages": [
      {
        "role": "user",
        "content": "你好，请介绍一下 Python 语言"
      }
    ],
    "stream": false
  }'

# 流式响应（逐字返回，体验更好）
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "grok-4-fast",
    "messages": [
      {
        "role": "user",
        "content": "写一个快速排序算法的 Python 实现"
      }
    ],
    "stream": true
  }'
```

**参数说明：**
- `model`: 模型名称，可选值见下方【可用模型一览】表格
- `messages`: 对话消息数组，支持多轮对话
- `stream`: 是否启用流式响应，`true` 为流式，`false` 为非流式
- `temperature`: （可选）控制随机性，0-2 之间，默认 1.0
- `max_tokens`: （可选）最大生成 token 数

### 对话中带图片（图像分析）

OpenAI 标准的图片分析格式：

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "grok-4-fast",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "这张图片里有什么？"
          },
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/image.jpg"
            }
          }
        ]
      }
    ]
  }'
```

### 关于 `x_statsig_id`

- `x_statsig_id` 是 Grok 用于反机器人的 Token，有逆向资料可参考
- **建议新手勿修改配置，保留默认值即可**
- 尝试用 Camoufox 绕过 403 自动获 id，但 grok 现已限制非登陆的`x_statsig_id`，故弃用，采用固定值以兼容所有请求



## 如何部署

### 方法一：使用 docker-compose（推荐）

```yaml
services:
  grok2api:
    build: .
    image: grok2api
    container_name: grok2api
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - /root/grok2api/data:/app/data
      - /root/grok2api/logs:/app/logs
```

数据将持久化存储在 `grok_data` Docker 卷中。

### 方法二：本地直接部署（无 Docker）

#### 前置条件

- Python 3.10+（推荐 3.11）
- pip 包管理器
- 有效的 Grok SSO Token

#### 部署步骤

**步骤 1：创建虚拟环境（推荐）**

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

**步骤 2：安装依赖**

```bash
pip install -r requirements.txt
```

**步骤 3：准备配置文件**

项目提供了示例文件 `data/setting.example.toml`，先复制一份并编辑：

```bash
cp data/setting.example.toml data/setting.toml
```

然后打开 `data/setting.toml`，配置以下必填项：

```toml
[grok]
# 必须配置 x_statsig_id（项目已有默认值，通常无需修改）
x_statsig_id = "ZTpUeXBlRXJyb3I6IENhbm5vdCByZWFkIHByb3BlcnRpZXMgb2YgdW5kZWZpbmVkIChyZWFkaW5nICdjaGlsZE5vZGVzJyk="

# 可选配置
api_key = ""                    # API 密钥（如需保护API访问）
proxy_url = ""                  # 代理服务器（访问 Grok API 用）
cf_clearance = ""               # Cloudflare token（如被拦截）

[global]
log_level = "INFO"              # 日志级别：DEBUG/INFO/WARNING/ERROR
```

**步骤 4：准备 Token 文件**

项目提供了示例文件 `data/token.example.json`，先复制一份并编辑：

```bash
cp data/token.example.json data/token.json
```

然后打开 `data/token.json`，将示例 Token 替换为你的真实 Grok SSO Token：

```json
{
  "sso": {
    "your-sso-token-here": {
      "remainingQueries": -1,
      "heavyremainingQueries": -1
    }
  },
  "ssoSuper": {}
}
```
> **注意：** `remainingQueries` 和 `heavyremainingQueries` 设置为 `-1` 即可，系统会在初次使用时自动同步官方剩余次数。

**如何获取 Token：**
1. 登录 grok.com
2. F12 → Application → Cookies
3. 复制 `sso` 或 `sso-rw` 的值

支持配置多个 Token，系统会自动在可用 Token 间进行负载均衡。

> **⚠️ 重要提示**: 
> - `setting.toml` 和 `token.json` 包含敏感信息，已在 `.gitignore` 中排除
> - 请勿将真实配置文件上传到版本控制系统
> - 示例文件（`*.example.toml` / `*.example.json`）可以安全上传

**步骤 5：启动服务**

```bash
# 方式1：使用 uvicorn 直接启动（推荐开发用）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 方式2：使用 Python 运行
python main.py
```

**步骤 6：访问验证**

- 健康检查：http://localhost:8000/health

**生产环境部署建议**

使用 pm2 进行进程管理：

```bash
# 安装 pm2
npm install -g pm2

# 启动应用
pm2 start main.py --name grok2api --interpreter python3

# 查看状态
pm2 status

# 查看日志
pm2 logs grok2api

# 其他命令
pm2 restart grok2api  # 重启
pm2 stop grok2api     # 停止
pm2 delete grok2api   # 删除
```

## 接口说明

> 与 OpenAI 官方接口完全兼容，API 请求需通过 **Authorization header** 认证

| 方法  | 端点                         | 描述                               | 是否需要认证 |
|-------|------------------------------|------------------------------------|------|
| POST  | `/v1/chat/completions`       | 创建聊天对话（流式/非流式）         | ✅   |
| GET   | `/v1/models`                 | 获取全部支持模型                   | ✅   |


## 可用模型一览

| 模型名称               | 计次   | 账户类型      | 图像生成/编辑 | 深度思考 | 联网搜索 | 视频生成 |
|------------------------|--------|--------------|--------------|----------|----------|----------|
| `grok-4.1`             | 1      | Basic/Super  | ✅           | ✅       | ✅       | ❌       |
| `grok-4.1-thinking`    | 1      | Basic/Super  | ✅           | ✅       | ✅       | ❌       |
| `grok-imagine-0.9`     | -      | Basic/Super  | ✅           | ❌       | ❌       | ✅       |
| `grok-4-fast`          | 1      | Basic/Super  | ✅           | ✅       | ✅       | ❌       |
| `grok-4-fast-expert`   | 4      | Basic/Super  | ✅           | ✅       | ✅       | ❌       |
| `grok-4-expert`        | 4      | Basic/Super  | ✅           | ✅       | ✅       | ❌       |
| `grok-4-heavy`         | 1      | Super        | ✅           | ✅       | ✅       | ❌       |
| `grok-3-fast`          | 1      | Basic/Super  | ✅           | ❌       | ✅       | ❌       |

## 项目架构

### 1. 架构概览
```
客户端/SDK
    │
    ▼
FastAPI 路由 (app/api/v1)
    │  OpenAI Schema 兼容
    ▼
服务层 (app/services/grok)
    │  Token 池管理 · 上传能力 · 请求加工
    ▼
Grok API 客户端 (curl_cffi 伪装)
    │
    ▼
Grok API
```
- 分层设计：API 层 → 服务层 → Grok API
- 模块组织：`app/api`, `app/core`, `app/models`, `app/services`

### 2. 目录结构
```
├── main.py                 # 应用入口，启动 FastAPI/Uvicorn
├── app
│   ├── api                 # API 层入口
│   │   └── v1
│   │       ├── chat.py     # /v1/chat/completions 路由与处理
│   │       └── models.py   # /v1/models 路由与处理
│   ├── core                # 核心支撑能力
│   │   ├── auth.py         # 鉴权与令牌校验
│   │   ├── config.py       # 配置加载与全局设置
│   │   ├── exception.py    # 统一异常封装
│   │   ├── logger.py       # 日志初始化
│   │   └── storage.py      # 本地/临时存储抽象
│   ├── models              # 数据模型与协议定义
│   │   ├── grok_models.py  # Grok 专用模型枚举与结构
│   │   └── openai_schema.py# OpenAI 兼容请求/响应 Schema
│   └── services
│       └── grok            # 与 Grok API 的交互实现
│           ├── client.py   # HTTP 客户端封装（curl_cffi）
│           ├── processer.py# 请求预处理与响应后处理
│           ├── upload.py   # 图片上传
│           ├── create.py   # 聊天/补全创建
│           ├── token.py    # Token 池与负载均衡
│           └── statsig.py  # 反爬/指纹相关参数
├── data/setting.toml       # 配置文件
├── docker-compose.yml      # 容器编排
├── Dockerfile              # 镜像构建
├── logs/                   # 默认日志输出目录
└── requirements.txt        # 依赖列表
```

### 3. 核心模块说明
| 层级 | 位置 | 关键文件 | 职责 |
|------|------|----------|------|
| API 层 | `app/api/v1/` | `chat.py` | 提供 `/v1/chat/completions` 路由，处理流式/非流式聊天请求，协调服务层。 |
|  |  | `models.py` | 提供 `/v1/models` 路由，列出可用模型并返回 OpenAI 兼容格式。 |
| 核心层 | `app/core/` | `auth.py` | 认证与令牌校验、请求签名相关逻辑。 |
|  |  | `config.py` | 读取 `data/setting.toml`，初始化全局配置。 |
|  |  | `exception.py` | 统一异常类型与错误码映射。 |
|  |  | `logger.py` | 日志配置与结构化输出。 |
|  |  | `storage.py` | 本地/临时存储抽象，支持上传缓存。 |
| 模型层 | `app/models/` | `grok_models.py` | Grok 模型清单、定价和能力标注。 |
|  |  | `openai_schema.py` | OpenAI 兼容的请求/响应 Pydantic 模型定义。 |
| 服务层 | `app/services/grok/` | `client.py` | 基于 `curl_cffi` 的 HTTP 客户端，伪装浏览器指纹。 |
|  |  | `processer.py` | OpenAI→Grok 参数转换、响应清洗与格式统一。 |
|  |  | `upload.py` | 图片上传到 Grok 的封装。 |
|  |  | `create.py` | 核心创建对话/补全逻辑，驱动流式与非流式。 |
|  |  | `token.py` | Token 池管理、自动轮询与负载均衡。 |
|  |  | `statsig.py` | 反爬与 Statsig 相关参数处理。 |

### 4. 请求处理流程
1. 客户端请求进入 API 层，完成鉴权与基本校验。  
2. 请求体由 OpenAI Schema 转换为 Grok 所需格式。  
3. 根据配置选择可用 Token，执行轮询/负载均衡。  
4. 如包含图片，先上传并替换为 Grok 可识别的 URL。  
5. 构造最终请求，通过 `curl_cffi` 发送到 Grok API。  
6. 接收响应（支持流式与非流式），处理错误和超时。  
7. 将 Grok 响应转换回 OpenAI 兼容格式，返回客户端。  

### 5. 技术栈
- Web 框架：FastAPI + Uvicorn  
- HTTP 客户端：curl_cffi（浏览器指纹伪装）  
- 序列化：orjson（高性能 JSON）  
- 异步 IO：asyncio + aiofiles  
- 配置管理：TOML  

### 6. 关键特性
- Token 池管理与自动负载均衡  
- 流式与非流式响应支持  
- 图片/视频生成（直接返回 Grok URL）  
- 完整的异常处理与日志记录  
- OpenAI 兼容接口  


## 配置参数说明

> **注意**：配置参数需通过编辑 `data/setting.toml` 文件进行设置。

| 参数名                     | 作用域  | 必填 | 说明                                    | 默认值 |
|----------------------------|---------|------|-----------------------------------------|--------|
| log_level                  | global  | 否   | 日志级别：DEBUG/INFO/...                | "INFO" |
| api_key                    | grok    | 否   | API 密钥（可选加强安全）                | ""     |
| proxy_url                  | grok    | 否   | HTTP代理服务器地址                      | ""     |
| stream_chunk_timeout       | grok    | 否   | 流式分块超时时间(秒)                     | 120    |
| stream_first_response_timeout | grok | 否   | 流式首次响应超时时间(秒)                 | 30     |
| stream_total_timeout       | grok    | 否   | 流式总超时时间(秒)                       | 600    |
| cf_clearance               | grok    | 否   | Cloudflare安全令牌                      | ""     |
| x_statsig_id               | grok    | 是   | 反机器人唯一标识符                      | "ZTpUeXBlRXJyb3I6IENhbm5vdCByZWFkIHByb3BlcnRpZXMgb2YgdW5kZWZpbmVkIChyZWFkaW5nICdjaGlsZE5vZGVzJyk=" |
| filtered_tags              | grok    | 否   | 过滤响应标签（逗号分隔）                | "xaiartifact,xai:tool_usage_card,grok:render" |
| show_thinking              | grok    | 否   | 显示思考过程 true(显示)/false(隐藏)     | true   |
| temporary                  | grok    | 否   | 会话模式 true(临时)/false               | true   |


## ⚠️ 注意事项

本项目仅供学习与研究，请遵守相关使用条款！

> 本项目基于以下项目学习重构，特别感谢：[chenyme/grok2api](https://github.com/chenyme/grok2api)
