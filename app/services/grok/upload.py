"""图片上传管理器 - 支持Base64和URL图片上传"""

import base64
import ipaddress
import re
import socket
from typing import Tuple, Optional, Union
from urllib.parse import urlparse
from curl_cffi.requests import AsyncSession

from app.services.grok.statsig import get_dynamic_headers
from app.core.exception import GrokApiException
from app.core.config import setting
from app.core.logger import logger


# 常量
UPLOAD_API = "https://grok.com/rest/app-chat/upload-file"
TIMEOUT = 30
BROWSER = "chrome133a"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_MIME_PREFIX = "image/"
DISALLOWED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
DISALLOWED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
]
IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

# MIME类型
MIME_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
}
DEFAULT_MIME = "image/jpeg"
DEFAULT_EXT = "jpg"


class ImageUploadManager:
    """图片上传管理器"""

    @staticmethod
    async def upload(image_input: str, auth_token: str) -> Tuple[str, str]:
        """上传图片（支持Base64或URL）
        
        Returns:
            (file_id, file_uri) 元组
        """
        try:
            # 判断类型并处理
            if ImageUploadManager._is_url(image_input):
                buffer, mime = await ImageUploadManager._download(image_input)
                filename, _ = ImageUploadManager._get_info("", mime)
            else:
                buffer = image_input.split(",")[1] if "data:image" in image_input else image_input
                filename, mime = ImageUploadManager._get_info(image_input)

            if not buffer:
                raise GrokApiException("图片内容为空", "API_ERROR")

            # 构建数据
            data = {
                "fileName": filename,
                "fileMimeType": mime,
                "content": buffer,
            }

            if not auth_token:
                raise GrokApiException("认证令牌缺失", "NO_AUTH_TOKEN")

            # 请求配置
            cf = setting.grok_config.get("cf_clearance", "")
            headers = {
                **get_dynamic_headers("/rest/app-chat/upload-file"),
                "Cookie": f"{auth_token};{cf}" if cf else auth_token,
            }
            
            proxy = setting.grok_config.get("proxy_url", "")
            proxies = {"http": proxy, "https": proxy} if proxy else None

            # 上传
            async with AsyncSession() as session:
                response = await session.post(
                    UPLOAD_API,
                    headers=headers,
                    json=data,
                    impersonate=BROWSER,
                    timeout=TIMEOUT,
                    proxies=proxies,
                )

                if response.status_code != 200:
                    raise GrokApiException(
                        f"图片上传失败，状态码: {response.status_code}",
                        "API_ERROR",
                        context={"status": response.status_code}
                    )

                result = response.json()
                file_id = result.get("fileMetadataId")
                file_uri = result.get("fileUri")
                if not file_id or not file_uri:
                    raise GrokApiException("上传返回异常，缺少文件信息", "API_ERROR")

                logger.debug(f"[Upload] 成功，ID: {file_id}")
                return file_id, file_uri

        except GrokApiException:
            raise
        except Exception as e:
            logger.warning(f"[Upload] 失败: {e}")
            raise GrokApiException("图片上传失败", "API_ERROR") from e

    @staticmethod
    def _is_url(input_str: str) -> bool:
        """检查是否为URL"""
        try:
            result = urlparse(input_str)
            return result.scheme.lower() == 'https' and bool(result.netloc)
        except Exception:
            return False

    @staticmethod
    async def _download(url: str) -> Tuple[str, str]:
        """下载图片并转Base64
        
        Returns:
            (base64_string, mime_type) 元组
        """
        try:
            ImageUploadManager._validate_https_url(url)

            proxy = setting.grok_config.get("proxy_url", "")
            proxies = {"http": proxy, "https": proxy} if proxy else None

            async with AsyncSession() as session:
                response = await session.get(
                    url,
                    timeout=5,
                    proxies=proxies,
                    impersonate=BROWSER,
                )
                response.raise_for_status()

                content_length = response.headers.get('content-length')
                try:
                    if content_length and int(content_length) > MAX_FILE_SIZE:
                        raise GrokApiException("文件过大", "FILE_TOO_LARGE")
                except ValueError:
                    pass

                content = response.content
                if len(content) > MAX_FILE_SIZE:
                    raise GrokApiException("文件过大", "FILE_TOO_LARGE")

                content_type = response.headers.get('content-type', DEFAULT_MIME)
                mime_type = content_type.split(';')[0].strip().lower() if content_type else DEFAULT_MIME
                if not mime_type.startswith(ALLOWED_MIME_PREFIX):
                    raise GrokApiException("仅允许图片类型", "INVALID_CONTENT_TYPE")

                b64 = base64.b64encode(content).decode()
                return b64, mime_type
        except GrokApiException:
            raise
        except Exception as e:
            logger.warning(f"[Upload] 下载失败: {e}")
            raise GrokApiException("图片下载失败", "API_ERROR") from e

    @staticmethod
    def _validate_https_url(url: str) -> None:
        """验证URL协议与主机是否合法"""
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme != "https" or not parsed.hostname:
            raise GrokApiException("仅允许HTTPS地址", "INVALID_URL")

        hostname = parsed.hostname.lower()
        if ImageUploadManager._is_disallowed_host(hostname):
            raise GrokApiException("禁止访问内网地址", "INVALID_URL")

    @staticmethod
    def _is_disallowed_host(hostname: str) -> bool:
        """检查主机是否在黑名单或私网段"""
        if hostname in DISALLOWED_HOSTS:
            return True

        try:
            ip_obj = ipaddress.ip_address(hostname)
            return ImageUploadManager._ip_in_disallowed_network(ip_obj)
        except ValueError:
            return ImageUploadManager._resolve_and_validate(hostname)

    @staticmethod
    def _resolve_and_validate(hostname: str) -> bool:
        """解析域名并判断是否落在内网"""
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False

        for info in addr_info:
            ip_str = info[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ImageUploadManager._ip_in_disallowed_network(ip_obj):
                return True
        return False

    @staticmethod
    def _ip_in_disallowed_network(ip_obj: IPAddress) -> bool:
        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
            return True

        for network in DISALLOWED_NETWORKS:
            if ip_obj.version == network.version and ip_obj in network:
                return True
        return False

    @staticmethod
    def _get_info(image_data: str, mime_type: Optional[str] = None) -> Tuple[str, str]:
        """获取文件名和MIME类型
        
        Returns:
            (file_name, mime_type) 元组
        """
        # 已提供MIME类型
        if mime_type:
            ext = mime_type.split("/")[1] if "/" in mime_type else DEFAULT_EXT
            return f"image.{ext}", mime_type

        # 从Base64提取
        mime = DEFAULT_MIME
        ext = DEFAULT_EXT

        if "data:image" in image_data:
            if match := re.search(r"data:([a-zA-Z0-9]+/[a-zA-Z0-9-.+]+);base64,", image_data):
                mime = match.group(1)
                ext = mime.split("/")[1]

        return f"image.{ext}", mime
