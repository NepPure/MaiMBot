from dataclasses import dataclass
from typing import Dict, Optional, List, Union
import html
import requests
import base64
from PIL import Image
import io 
from .image_utils import storage_compress_image, storage_emoji
import os
from random import random
from nonebot.adapters.onebot.v11 import Bot
from .config import global_config, llm_config
import time
import asyncio

#解析各种CQ码
#包含CQ码类




@dataclass
class CQCode:
    """
    CQ码数据类，用于存储和处理CQ码
    
    属性:
        type: CQ码类型（如'image', 'at', 'face'等）
        params: CQ码的参数字典
        raw_code: 原始CQ码字符串
        translated_plain_text: 经过处理（如AI翻译）后的文本表示
    """
    type: str
    params: Dict[str, str]
    # raw_code: str
    group_id: int
    user_id: int
    group_name: str = ""
    user_nickname: str = ""
    translated_plain_text: Optional[str] = None
    reply_message: Dict = None  # 存储回复消息
    image_base64: Optional[str] = None
    
    @classmethod
    def from_cq_code(cls, cq_code: str, reply: Dict = None) -> 'CQCode':
        """
        从CQ码字符串创建CQCode对象
        例如：[CQ:image,file=1.jpg,url=http://example.com/1.jpg]
        """
        if not cq_code.startswith('[CQ:'):
            return cls('text', {'text': cq_code}, cq_code, group_id=0, user_id=0)
        
        # 移除前后的[]
        content = cq_code[1:-1]
        # 分离类型和参数部分
        parts = content.split(',')
        if not parts:
            return cls('text', {'text': cq_code}, cq_code, group_id=0, user_id=0)
            
        # 获取CQ类型
        cq_type = parts[0][3:]  # 去掉'CQ:'
        
        # 解析参数
        params = {}
        for part in parts[1:]:
            if '=' in part:
                key, value = part.split('=', 1)
                # 处理转义字符
                value = cls.unescape(value)
                params[key] = value
        
        # 创建实例
        instance = cls(cq_type, params, cq_code, group_id=0, user_id=0, reply_message=reply)
        # 根据类型进行相应的翻译处理
        instance.translate()
        return instance

    def translate(self):
        """根据CQ码类型进行相应的翻译处理"""
        if self.type == 'text':
            self.translated_plain_text = self.params.get('text', '')
        elif self.type == 'image':
            if self.params.get('sub_type') == '0':
                self.translated_plain_text = self.translate_image()
            else:
                self.translated_plain_text = self.translate_emoji()
        elif self.type == 'at':
            from .message import Message
            message_obj = Message(
                user_id=str(self.params.get('qq', ''))
            )
            self.translated_plain_text = f"@{message_obj.user_nickname}"
        elif self.type == 'reply':
            self.translated_plain_text = self.translate_reply()
        elif self.type == 'face':
            face_id = self.params.get('id', '')
            # self.translated_plain_text = f"[表情{face_id}]"
            self.translated_plain_text = f"[表情]"
        elif self.type == 'forward':
            self.translated_plain_text = self.translate_forward()
        else:
            self.translated_plain_text = f"[{self.type}]"

    def get_img(self):
        # 创建自定义 SSL 上下文 (核心修改点),很蛋疼的问题只能TLS1.2请求，1.3报错，Linux高版本就是有问题
        import ssl
        from urllib3.util.ssl_ import create_urllib3_context
        from requests.adapters import HTTPAdapter

        # 配置仅允许 TLS1.2
        tls_ctx = create_urllib3_context()
        tls_ctx.options |= ssl.OP_NO_SSLv3 | ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_3
        tls_ctx.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256')

        # 创建专用会话
        session = requests.Session()
        session.mount('https://', HTTPAdapter(max_retries=3, ssl_context=tls_ctx))

        # 优化后的请求头 (保持原有格式但修复编码问题)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.87 Safari/537.36',
            'Accept': 'text/html, application/xhtml+xml, */*',  # 修正缺失的加号
            'Accept-Encoding': 'gzip, deflate, br',  # 改用标准编码
            'Accept-Language': 'zh-CN',  # 修正大小写
            'Cache-Control': 'no-cache'
        }

        url = html.unescape(self.params['url'])
        if not url.startswith(('http://', 'https://')):
            return None

        try:
            # 使用专用会话发送请求
            response = session.get(
                url,
                headers=headers,
                timeout=10,
                verify=False,  # 保持原有验证设置
                allow_redirects=True
            )
            
            # 状态码处理逻辑
            if response.status_code == 400 and 'multimedia.nt.qq.com.cn' in url:
                return None  # 腾讯特殊处理
            
            response.raise_for_status()  # 自动处理非200状态码
            
            # 内容类型验证
            if not response.headers.get('content-type', '').startswith('image/'):
                print(f"\033[1;31m[警告]\033[0m 非图片类型响应: {response.headers.get('content-type')}")
                return None
                
            return base64.b64encode(response.content).decode('utf-8')
            
        except requests.RequestException as e:
            print(f"\033[1;31m[错误]\033[0m 请求失败: {str(e)}")
            return None
    
    def translate_emoji(self) -> str:
        """处理表情包类型的CQ码"""
        if 'url' not in self.params:
            return '[表情包]'
        base64 = self.get_img()
        if base64:
            return self.get_image_description(base64)
        else:
            return '[表情包]'
    
    
    def translate_image(self) -> str:
        """处理图片类型的CQ码，区分普通图片和表情包"""
        #没有url，直接返回默认文本
        if 'url' not in self.params:
            return '[图片]'
        base64 = self.get_img()
        if base64:
            return self.get_image_description(base64)
        else:
            return '[图片]'

    def get_emoji_description(self, image_base64: str) -> str:
        """调用AI接口获取表情包描述"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.SILICONFLOW_API_KEY}"
        }
        
        payload = {
            "model": "deepseek-ai/deepseek-vl2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "这是一个表情包，请用简短的中文描述这个表情包传达的情感和含义。最多20个字。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 50,
            "temperature": 0.4
        }
        
        response = requests.post(
            f"{llm_config.SILICONFLOW_BASE_URL}chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result_json = response.json()
            if "choices" in result_json and len(result_json["choices"]) > 0:
                description = result_json["choices"][0]["message"]["content"]
                return f"[表情包：{description}]"
        
        raise ValueError(f"AI接口调用失败: {response.text}")

    def get_image_description(self, image_base64: str) -> str:
        """调用AI接口获取普通图片描述"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.SILICONFLOW_API_KEY}"
        }
        
        payload = {
            "model": "deepseek-ai/deepseek-vl2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请用中文描述这张图片的内容。如果有文字，请把文字都描述出来。并尝试猜测这个图片的含义。最多200个字。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 300,
            "temperature": 0.6
        }
        
        response = requests.post(
            f"{llm_config.SILICONFLOW_BASE_URL}chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result_json = response.json()
            if "choices" in result_json and len(result_json["choices"]) > 0:
                description = result_json["choices"][0]["message"]["content"]
                return f"[图片：{description}]"
        
        raise ValueError(f"AI接口调用失败: {response.text}")
    
    def translate_forward(self) -> str:
        """处理转发消息"""
        try:
            if 'content' not in self.params:
                return '[转发消息]'
            
            # 解析content内容（需要先反转义）
            content = self.unescape(self.params['content'])
            # print(f"\033[1;34m[调试信息]\033[0m 转发消息内容: {content}")
            # 将字符串形式的列表转换为Python对象
            import ast
            try:
                messages = ast.literal_eval(content)
            except ValueError as e:
                print(f"\033[1;31m[错误]\033[0m 解析转发消息内容失败: {str(e)}")
                return '[转发消息]'
            
            # 处理每条消息
            formatted_messages = []
            for msg in messages:
                sender = msg.get('sender', {})
                nickname = sender.get('card') or sender.get('nickname', '未知用户')
                
                # 获取消息内容并使用Message类处理
                raw_message = msg.get('raw_message', '')
                message_array = msg.get('message', [])
                
                if message_array and isinstance(message_array, list):
                    # 检查是否包含嵌套的转发消息
                    for message_part in message_array:
                        if message_part.get('type') == 'forward':
                            content = '[转发消息]'
                            break
                    else:
                        # 处理普通消息
                        if raw_message:
                            from .message import Message
                            message_obj = Message(
                                user_id=msg.get('user_id', 0),
                                message_id=msg.get('message_id', 0),
                                raw_message=raw_message,
                                plain_text=raw_message,
                                group_id=msg.get('group_id', 0)
                            )
                            content = message_obj.processed_plain_text
                        else:
                            content = '[空消息]'
                else:
                    # 处理普通消息
                    if raw_message:
                        from .message import Message
                        message_obj = Message(
                            user_id=msg.get('user_id', 0),
                            message_id=msg.get('message_id', 0),
                            raw_message=raw_message,
                            plain_text=raw_message,
                            group_id=msg.get('group_id', 0)
                        )
                        content = message_obj.processed_plain_text
                    else:
                        content = '[空消息]'
                
                formatted_msg = f"{nickname}: {content}"
                formatted_messages.append(formatted_msg)
            
            # 合并所有消息
            combined_messages = '\n'.join(formatted_messages)
            print(f"\033[1;34m[调试信息]\033[0m 合并后的转发消息: {combined_messages}")
            return f"[转发消息:\n{combined_messages}]"
            
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 处理转发消息失败: {str(e)}")
            return '[转发消息]'

    def translate_reply(self) -> str:
        """处理回复类型的CQ码"""

        # 创建Message对象
        from .message import Message
        if self.reply_message == None:
            return '[回复某人消息]'
        
        if self.reply_message.sender.user_id:
            message_obj = Message(
                user_id=self.reply_message.sender.user_id,
                message_id=self.reply_message.message_id,
                raw_message=str(self.reply_message.message),
                group_id=self.group_id
            )
            if message_obj.user_id == global_config.BOT_QQ:
                return f"[回复 {global_config.BOT_NICKNAME} 的消息: {message_obj.processed_plain_text}]"
            else:
                return f"[回复 {self.reply_message.sender.nickname} 的消息: {message_obj.processed_plain_text}]"

        else:
            return '[回复某人消息]'

    @staticmethod
    def unescape(text: str) -> str:
        """反转义CQ码中的特殊字符"""
        return text.replace('&#44;', ',') \
                  .replace('&#91;', '[') \
                  .replace('&#93;', ']') \
                  .replace('&amp;', '&')

    @staticmethod
    def create_emoji_cq(file_path: str) -> str:
        """
        创建表情包CQ码
        Args:
            file_path: 本地表情包文件路径
        Returns:
            表情包CQ码字符串
        """
        # 确保使用绝对路径
        abs_path = os.path.abspath(file_path)
        # 转义特殊字符
        escaped_path = abs_path.replace('&', '&amp;') \
                             .replace('[', '&#91;') \
                             .replace(']', '&#93;') \
                             .replace(',', '&#44;')
        # 生成CQ码，设置sub_type=1表示这是表情包
        return f"[CQ:image,file=file:///{escaped_path},sub_type=1]"
    
class CQCode_tool:
    @staticmethod
    def cq_from_dict_to_class(cq_code: Dict, reply: Optional[Dict] = None) -> CQCode:
        """
        将CQ码字典转换为CQCode对象
        
        Args:
            cq_code: CQ码字典
            reply: 回复消息的字典（可选）
            
        Returns:
            CQCode对象
        """
        # 处理字典形式的CQ码
        # 从cq_code字典中获取type字段的值,如果不存在则默认为'text'
        cq_type = cq_code.get('type', 'text')
        params = {}
        if cq_type == 'text':
            params['text'] = cq_code.get('data', {}).get('text', '')
        else:
            params = cq_code.get('data', {})
        
        instance = CQCode(
            type=cq_type,
            params=params,
            group_id=0,
            user_id=0,
            reply_message=reply
        )
        
        # 进行翻译处理
        instance.translate()
        return instance
    
    @staticmethod
    def create_reply_cq(message_id: int) -> str:
        """
        创建回复CQ码
        Args:
            message_id: 回复的消息ID
        Returns:
            回复CQ码字符串
        """
        return f"[CQ:reply,id={message_id}]"
    
    
cq_code_tool = CQCode_tool()
