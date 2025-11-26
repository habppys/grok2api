"""认证模块 - API令牌验证"""

from typing import Optional
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import setting
from app.core.logger import logger


# Bearer安全方案
security = HTTPBearer(auto_error=False)


def _build_error(message: str, code: str = "invalid_token") -> dict:
    """构建认证错误"""
    return {
        "error": {
            "message": message,
            "type": "authentication_error",
            "code": code
        }
    }


class AuthManager:
    """认证管理器 - 验证API令牌"""

    @staticmethod
    def verify(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[str]:
        """验证令牌（Fail Closed）"""
        api_key = setting.grok_config.get("api_key")
        allow_anonymous = setting.grok_config.get("allow_anonymous_access", False)

        # 未设置 API_KEY 时的安全策略
        if not api_key:
            if allow_anonymous:
                logger.warning("[Auth] 匿名访问已启用（安全风险）")
                return credentials.credentials if credentials else None
            else:
                logger.error("[Auth] API_KEY 未配置且未启用匿名访问，拒绝请求（Fail Closed）")
                raise HTTPException(
                    status_code=401,
                    detail=_build_error("服务未配置认证密钥，请联系管理员", "auth_not_configured")
                )

        # 检查令牌
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail=_build_error("缺少认证令牌", "missing_token")
            )

        # 验证令牌
        if credentials.credentials != api_key:
            raise HTTPException(
                status_code=401,
                detail=_build_error(f"令牌无效，长度: {len(credentials.credentials)}", "invalid_token")
            )

        logger.debug("[Auth] 令牌认证成功")
        return credentials.credentials


# 全局实例
auth_manager = AuthManager()