"""FastAPI应用主入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.logger import logger
from app.core.exception import register_exception_handlers
from app.core.storage import storage_manager
from app.core.config import setting
from app.services.grok.token import token_manager
from app.api.v1.chat import router as chat_router
from app.api.v1.models import router as models_router


# 定义应用生命周期
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    启动顺序:
    1. 初始化核心服务 (storage, settings, token_manager)

    关闭顺序 (LIFO):
    1. 关闭核心服务
    """
    # --- 启动过程 ---
    # 1. 初始化核心服务
    await storage_manager.init()

    # 设置存储到配置和token管理器
    storage = storage_manager.get_storage()
    setting.set_storage(storage)
    token_manager.set_storage(storage)

    # 重新加载配置和token数据
    await setting.reload()
    token_manager._load_data()
    logger.info("[Grok2API] 核心服务初始化完成")

    logger.info("[Grok2API] 应用启动成功")

    try:
        yield
    finally:
        # --- 关闭过程 ---
        # 关闭核心服务
        await storage_manager.close()
        logger.info("[Grok2API] 应用关闭成功")


# 初始化日志
logger.info("[Grok2API] 应用正在启动...")

# 创建FastAPI应用
app = FastAPI(
    title="Grok2API",
    description="Grok API 转换服务",
    version="1.3.1",
    lifespan=lifespan
)

# 注册全局异常处理器
register_exception_handlers(app)

# 注册路由
app.include_router(chat_router, prefix="/v1")
app.include_router(models_router, prefix="/v1")


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "service": "Grok2API",
        "version": "1.0.3"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
