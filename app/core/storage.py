"""存储抽象层 - 仅支持文件存储"""

import orjson
import toml
import asyncio
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional

from app.core.logger import logger


class FileStorage:
    """文件存储"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.token_file = data_dir / "token.json"
        self.config_file = data_dir / "setting.toml"
        self._token_lock = asyncio.Lock()
        self._config_lock = asyncio.Lock()

    async def init_db(self) -> None:
        """初始化文件存储"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if not self.token_file.exists():
            await self._write(self.token_file, orjson.dumps({"sso": {}, "ssoSuper": {}}, option=orjson.OPT_INDENT_2).decode())
            logger.info("[Storage] 创建token文件")

        if not self.config_file.exists():
            default = {
                "global": {"api_keys": []},
                "grok": {"proxy_url": "", "cf_clearance": "", "x_statsig_id": ""}
            }
            await self._write(self.config_file, toml.dumps(default))
            logger.info("[Storage] 创建配置文件")

    async def _read(self, path: Path) -> str:
        """读取文件"""
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return await f.read()

    async def _write(self, path: Path, content: str) -> None:
        """写入文件"""
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def _load_json(self, path: Path, default: Dict, lock: asyncio.Lock) -> Dict[str, Any]:
        """加载JSON"""
        try:
            async with lock:
                if not path.exists():
                    return default
                return orjson.loads(await self._read(path))
        except Exception as e:
            logger.error(f"[Storage] 加载{path.name}失败: {e}")
            return default

    async def _save_json(self, path: Path, data: Dict, lock: asyncio.Lock) -> None:
        """保存JSON"""
        try:
            async with lock:
                await self._write(path, orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
        except Exception as e:
            logger.error(f"[Storage] 保存{path.name}失败: {e}")
            raise

    async def _load_toml(self, path: Path, default: Dict, lock: asyncio.Lock) -> Dict[str, Any]:
        """加载TOML"""
        try:
            async with lock:
                if not path.exists():
                    return default
                return toml.loads(await self._read(path))
        except Exception as e:
            logger.error(f"[Storage] 加载{path.name}失败: {e}")
            return default

    async def _save_toml(self, path: Path, data: Dict, lock: asyncio.Lock) -> None:
        """保存TOML"""
        try:
            async with lock:
                await self._write(path, toml.dumps(data))
        except Exception as e:
            logger.error(f"[Storage] 保存{path.name}失败: {e}")
            raise

    async def load_tokens(self) -> Dict[str, Any]:
        """加载token"""
        return await self._load_json(self.token_file, {"sso": {}, "ssoSuper": {}}, self._token_lock)

    async def save_tokens(self, data: Dict[str, Any]) -> None:
        """保存token"""
        await self._save_json(self.token_file, data, self._token_lock)

    async def load_config(self) -> Dict[str, Any]:
        """加载配置"""
        return await self._load_toml(self.config_file, {"global": {}, "grok": {}}, self._config_lock)

    async def save_config(self, data: Dict[str, Any]) -> None:
        """保存配置"""
        await self._save_toml(self.config_file, data, self._config_lock)


class StorageManager:
    """存储管理器"""

    def __init__(self) -> None:
        self._storage: Optional[FileStorage] = None
        self._initialized: bool = False

    async def init(self) -> None:
        """初始化存储"""
        if self._initialized:
            return

        data_dir = Path(__file__).parents[2] / "data"
        self._storage = FileStorage(data_dir)

        await self._storage.init_db()
        self._initialized = True
        logger.info("[Storage] 使用文件存储模式")

    def get_storage(self) -> FileStorage:
        """获取存储实例"""
        if not self._initialized or not self._storage:
            raise RuntimeError("StorageManager未初始化")
        return self._storage

    async def close(self) -> None:
        """关闭存储（文件存储无需特殊操作）"""
        return


# 全局实例
storage_manager = StorageManager()
