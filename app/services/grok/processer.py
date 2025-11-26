"""Grok API 响应处理器 - 处理流式和非流式响应"""

import orjson
import uuid
import time
import asyncio
from typing import AsyncGenerator, Tuple, List

from app.core.config import setting
from app.core.exception import GrokApiException
from app.core.logger import logger
from app.models.openai_schema import (
    OpenAIChatCompletionResponse,
    OpenAIChatCompletionChoice,
    OpenAIChatCompletionMessage,
    OpenAIChatCompletionChunkResponse,
    OpenAIChatCompletionChunkChoice,
    OpenAIChatCompletionChunkMessage
)


class StreamTimeoutManager:
    """流式响应超时管理"""
    
    def __init__(self, chunk_timeout: int = 120, first_timeout: int = 30, total_timeout: int = 600):
        self.chunk_timeout = chunk_timeout
        self.first_timeout = first_timeout
        self.total_timeout = total_timeout
        self.start_time = asyncio.get_event_loop().time()
        self.last_chunk_time = self.start_time
        self.first_received = False
    
    def check_timeout(self) -> Tuple[bool, str]:
        """检查超时"""
        now = asyncio.get_event_loop().time()
        
        if not self.first_received and now - self.start_time > self.first_timeout:
            return True, f"首次响应超时({self.first_timeout}秒)"
        
        if self.total_timeout > 0 and now - self.start_time > self.total_timeout:
            return True, f"总超时({self.total_timeout}秒)"
        
        if self.first_received and now - self.last_chunk_time > self.chunk_timeout:
            return True, f"数据块超时({self.chunk_timeout}秒)"
        
        return False, ""
    
    def mark_received(self):
        """标记收到数据"""
        self.last_chunk_time = asyncio.get_event_loop().time()
        self.first_received = True
    
    def duration(self) -> float:
        """获取总耗时"""
        return asyncio.get_event_loop().time() - self.start_time


class GrokResponseProcessor:
    """Grok响应处理器"""

    @staticmethod
    async def process_normal(response, auth_token: str, model: str = None) -> OpenAIChatCompletionResponse:
        """处理非流式响应"""
        response_closed = False
        try:
            async for chunk in GrokResponseProcessor._iter_response_lines(response):
                if not chunk:
                    continue

                data = orjson.loads(chunk)

                # 错误检查
                if error := data.get("error"):
                    raise GrokApiException(
                        f"API错误: {error.get('message', '未知错误')}",
                        "API_ERROR",
                        {"code": error.get("code")}
                    )

                grok_resp = data.get("result", {}).get("response", {})
                
                # 视频响应
                if video_resp := grok_resp.get("streamingVideoGenerationResponse"):
                    if video_url := video_resp.get("videoUrl"):
                        content = await GrokResponseProcessor._build_video_content(video_url, auth_token)
                        result = GrokResponseProcessor._build_response(content, model or "grok-imagine-0.9")
                        response_closed = True
                        response.close()
                        return result

                # 模型响应
                model_response = grok_resp.get("modelResponse")
                if not model_response:
                    continue

                if error_msg := model_response.get("error"):
                    raise GrokApiException(f"模型错误: {error_msg}", "MODEL_ERROR")

                # 构建内容
                content = model_response.get("message", "")
                model_name = model_response.get("model")

                # 处理图片
                if images := model_response.get("generatedImageUrls"):
                    for img in images:
                        content += f"\n![Generated Image](https://assets.grok.com/{img})"

                result = GrokResponseProcessor._build_response(content, model_name)
                response_closed = True
                response.close()
                return result

            raise GrokApiException("无响应数据", "NO_RESPONSE")

        except orjson.JSONDecodeError as e:
            logger.error(f"[Processor] JSON解析失败: {e}")
            raise GrokApiException(f"JSON解析失败: {e}", "JSON_ERROR") from e
        except Exception as e:
            logger.error(f"[Processor] 处理错误: {type(e).__name__}: {e}")
            raise GrokApiException(f"响应处理错误: {e}", "STREAM_ERROR") from e
        finally:
            if not response_closed and hasattr(response, 'close'):
                try:
                    response.close()
                except Exception as e:
                    logger.warning(f"[Processor] 关闭响应失败: {e}")

    @staticmethod
    async def process_stream(response, auth_token: str) -> AsyncGenerator[str, None]:
        """处理流式响应"""
        is_image = False
        is_thinking = False
        thinking_finished = False
        model = None
        raw_filtered_tags = setting.grok_config.get("filtered_tags", "")
        if isinstance(raw_filtered_tags, str):
            filtered_tags = [tag.strip() for tag in raw_filtered_tags.split(",") if tag.strip()]
        else:
            filtered_tags = [str(tag).strip() for tag in raw_filtered_tags if str(tag).strip()]
        video_progress_started = False
        last_video_progress = -1
        response_closed = False
        show_thinking = setting.grok_config.get("show_thinking", True)

        timeout_mgr = StreamTimeoutManager(
            chunk_timeout=setting.grok_config.get("stream_chunk_timeout", 120),
            first_timeout=setting.grok_config.get("stream_first_response_timeout", 30),
            total_timeout=setting.grok_config.get("stream_total_timeout", 600)
        )

        def make_chunk(content: str, finish: str = None):
            chunk_data = OpenAIChatCompletionChunkResponse(
                id=f"chatcmpl-{uuid.uuid4()}",
                created=int(time.time()),
                model=model or "grok-4-mini-thinking-tahoe",
                choices=[OpenAIChatCompletionChunkChoice(
                    index=0,
                    delta=OpenAIChatCompletionChunkMessage(
                        role="assistant",
                        content=content
                    ) if content else {},
                    finish_reason=finish
                )]
            )
            return f"data: {chunk_data.model_dump_json()}\n\n"

        try:
            async for chunk in GrokResponseProcessor._iter_response_lines(response):
                is_timeout, timeout_msg = GrokResponseProcessor._handle_timeout_check(timeout_mgr)
                if is_timeout:
                    logger.warning(f"[Processor] {timeout_msg}")
                    yield make_chunk("", "stop")
                    yield "data: [DONE]\n\n"
                    return

                logger.debug(f"[Processor] 收到数据块: {len(chunk)} bytes")
                if not chunk:
                    continue

                try:
                    data = orjson.loads(chunk)

                    if error := data.get("error"):
                        error_msg = error.get('message', "未知错误")
                        logger.error(f"[Processor] API错误: {error_msg}")
                        yield make_chunk(f"Error: {error_msg}", "stop")
                        yield "data: [DONE]\n\n"
                        return

                    grok_resp = data.get("result", {}).get("response", {})
                    if not grok_resp:
                        continue

                    timeout_mgr.mark_received()

                    if user_resp := grok_resp.get("userResponse"):
                        if m := user_resp.get("model"):
                            model = m

                    handled_video, last_video_progress, video_progress_started, video_chunks = await GrokResponseProcessor._handle_video_progress(
                        grok_resp,
                        auth_token,
                        make_chunk,
                        last_video_progress,
                        video_progress_started,
                        show_thinking
                    )
                    for chunk_text in video_chunks:
                        yield chunk_text
                    if handled_video:
                        continue

                    image_handled, should_close_stream, is_image, image_chunks = await GrokResponseProcessor._handle_image_attachment(
                        grok_resp,
                        auth_token,
                        make_chunk,
                        is_image
                    )
                    for chunk_text in image_chunks:
                        yield chunk_text
                    if should_close_stream:
                        return
                    if image_handled:
                        continue

                    token = grok_resp.get("token", "")
                    text_chunks, is_thinking, thinking_finished = GrokResponseProcessor._handle_thinking_block(
                        grok_resp,
                        token,
                        filtered_tags,
                        show_thinking,
                        thinking_finished,
                        is_thinking,
                        make_chunk
                    )
                    for chunk_text in text_chunks:
                        yield chunk_text

                except (orjson.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning(f"[Processor] 解析失败: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"[Processor] 处理出错: {e}")
                    continue

            yield make_chunk("", "stop")
            yield "data: [DONE]\n\n"
            logger.info(f"[Processor] 流式完成，耗时: {timeout_mgr.duration():.2f}秒")

        except Exception as e:
            logger.error(f"[Processor] 严重错误: {e}")
            yield make_chunk(f"处理错误: {e}", "error")
            yield "data: [DONE]\n\n"
        finally:
            if not response_closed and hasattr(response, "close"):
                try:
                    response.close()
                    logger.debug("[Processor] 响应已关闭")
                except Exception as e:
                    logger.warning(f"[Processor] 关闭失败: {e}")

    @staticmethod
    def _handle_timeout_check(timeout_mgr: StreamTimeoutManager) -> Tuple[bool, str]:
        """处理超时检查"""
        return timeout_mgr.check_timeout()

    @staticmethod
    async def _handle_video_progress(
        grok_resp: dict,
        auth_token: str,
        make_chunk,
        last_video_progress: int,
        video_progress_started: bool,
        show_thinking: bool
    ) -> Tuple[bool, int, bool, List[str]]:
        """处理视频生成进度与结果"""
        video_resp = grok_resp.get("streamingVideoGenerationResponse")
        if not video_resp:
            return False, last_video_progress, video_progress_started, []

        chunks: List[str] = []
        progress = video_resp.get("progress", 0)
        v_url = video_resp.get("videoUrl")
        updated_progress = last_video_progress
        started = video_progress_started

        if progress > last_video_progress:
            updated_progress = progress
            if show_thinking:
                if not video_progress_started:
                    content = f"<think>视频已生成{progress}%\n"
                    started = True
                elif progress < 100:
                    content = f"视频已生成{progress}%\n"
                else:
                    content = f"视频已生成{progress}%</think>\n"
                chunks.append(make_chunk(content))

        if v_url:
            logger.debug("[Processor] 视频生成完成")
            video_content = await GrokResponseProcessor._build_video_content(v_url, auth_token)
            chunks.append(make_chunk(video_content))

        return True, updated_progress, started, chunks

    @staticmethod
    async def _handle_image_attachment(
        grok_resp: dict,
        auth_token: str,
        make_chunk,
        is_image: bool
    ) -> Tuple[bool, bool, bool, List[str]]:
        """处理图像流数据"""
        updated_is_image = is_image or bool(grok_resp.get("imageAttachmentInfo"))
        chunks: List[str] = []
        should_close = False

        if not updated_is_image:
            return False, False, updated_is_image, chunks

        model_resp = grok_resp.get("modelResponse")
        token = grok_resp.get("token", "")

        if model_resp:
            content_lines = []
            for img in model_resp.get("generatedImageUrls", []):
                try:
                    content_lines.append(f"![Generated Image](https://assets.grok.com/{img})")
                except Exception as e:
                    logger.warning(f"[Processor] 处理图片失败: {e}")
                    content_lines.append(f"![Generated Image](https://assets.grok.com/{img})")

            content = "\n".join(content_lines).strip()
            chunks.append(make_chunk(content, "stop"))
            should_close = True
        elif token:
            chunks.append(make_chunk(token))

        return True, should_close, updated_is_image, chunks

    @staticmethod
    def _handle_thinking_block(
        grok_resp: dict,
        token: str,
        filtered_tags: List[str],
        show_thinking: bool,
        thinking_finished: bool,
        is_thinking: bool,
        make_chunk
    ) -> Tuple[List[str], bool, bool]:
        """处理对话Token与思考状态"""
        chunks: List[str] = []

        if isinstance(token, list):
            return chunks, is_thinking, thinking_finished

        if not token:
            return chunks, is_thinking, thinking_finished

        if token and any(tag in token for tag in filtered_tags):
            return chunks, is_thinking, thinking_finished

        current_is_thinking = grok_resp.get("isThinking", False)
        if thinking_finished and current_is_thinking:
            return chunks, is_thinking, thinking_finished

        if grok_resp.get("toolUsageCardId"):
            if web_search := grok_resp.get("webSearchResults"):
                if current_is_thinking:
                    if show_thinking:
                        for result in web_search.get("results", []):
                            title = result.get("title", "")
                            url = result.get("url", "")
                            preview = result.get("preview", "")
                            preview_clean = preview.replace("\n", "") if isinstance(preview, str) else ""
                            token += f'\n- [{title}]({url} "{preview_clean}")'
                        token += "\n"
                    else:
                        return chunks, is_thinking, thinking_finished
                else:
                    return chunks, is_thinking, thinking_finished
            else:
                return chunks, is_thinking, thinking_finished

        message_tag = grok_resp.get("messageTag")
        content = token
        if message_tag == "header":
            content = f"\n\n{token}\n\n"

        should_skip = False
        if not is_thinking and current_is_thinking:
            if show_thinking:
                content = f"<think>\n{content}"
            else:
                should_skip = True
        elif is_thinking and not current_is_thinking:
            if show_thinking:
                content = f"\n</think>\n{content}"
            thinking_finished = True
        elif current_is_thinking and not show_thinking:
            should_skip = True

        if not should_skip:
            chunks.append(make_chunk(content))

        return chunks, current_is_thinking, thinking_finished

    @staticmethod
    async def _iter_response_lines(response):
        """在后台线程中迭代响应行，避免阻塞事件循环"""
        iterator = response.iter_lines()
        while True:
            chunk = await asyncio.to_thread(next, iterator, None)
            if chunk is None:
                break
            yield chunk

    @staticmethod
    async def _build_video_content(video_url: str, auth_token: str) -> str:
        """构建视频内容"""
        logger.debug(f"[Processor] 检测到视频: {video_url}")
        full_url = f"https://assets.grok.com/{video_url}"
        return f'<video src="{full_url}" controls="controls" width="500" height="300"></video>\\n'

    @staticmethod
    async def _append_images(content: str, images: list, auth_token: str) -> str:
        """追加图片到内容"""
        for img in images:
            try:
                content += f"\\n![Generated Image](https://assets.grok.com/{img})"
            except Exception as e:
                logger.warning(f"[Processor] 处理图片失败: {e}")
                content += f"\\n![Generated Image](https://assets.grok.com/{img})"
        
        return content

    @staticmethod
    def _build_response(content: str, model: str) -> OpenAIChatCompletionResponse:
        """构建响应对象"""
        return OpenAIChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[OpenAIChatCompletionChoice(
                index=0,
                message=OpenAIChatCompletionMessage(
                    role="assistant",
                    content=content
                ),
                finish_reason="stop"
            )],
            usage=None
        )
