from typing import List, Tuple, Type, Any, Dict
import datetime
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseEventHandler,
    EventType,
    MaiMessages,
    ConfigField,
    ComponentInfo,
)


class RepeatSameContentHandler(BaseEventHandler):
    """
    检测群内连续相同内容并复读的事件处理器
    """
    
    event_type = EventType.ON_MESSAGE
    handler_name = "repeat_same_content_handler"
    handler_description = "检测群内连续相同内容并复读"
    weight = 10  # 设置适当的权重
    intercept_message = False
    
    def __init__(self):
        super().__init__()
        # 存储每个群组的最近消息记录，格式：{group_id: [{'time': timestamp, 'content': message_content}, ...]}
        self.group_messages = {}
        # 存储每个群组最近复读的内容和时间，避免重复复读，格式：{group_id: {'content': str, 'timestamp': datetime}}
        self.last_repeated_content = {}
    
    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, None, None, None]:
        """
        执行事件处理，检测时间窗口和消息数量窗口内的相同内容并复读
        """
        if not message:
            return True, True, None, None, None
        
        # 只处理群消息
        if not message.is_group_message:
            return True, True, None, None, None
        
        # 获取群组ID和消息内容
        group_id = message.stream_id
        if not group_id:
            return True, True, None, None, None
        
        # 获取配置参数
        time_window_minutes = self.get_config("repeat.time_window_minutes", 5)  # x分钟内
        message_window_size = self.get_config("repeat.message_window_size", 10)  # y条消息内
        required_same_count = self.get_config("repeat.required_same_count", 3)  # z条相同消息
        max_message_length = self.get_config("repeat.max_message_length", 100)  # 最大消息长度限制
        repeat_cooldown_minutes = self.get_config("repeat.repeat_cooldown_minutes", 10)  # 同一内容复读冷却时间（分钟）
        
        # 获取消息的纯文本内容
        message_content = message.plain_text
        if not message_content or len(message_content) > max_message_length:
            return True, True, None, None, None
        
        # 获取当前时间
        current_time = datetime.datetime.now()
        
        # 初始化群组消息记录
        if group_id not in self.group_messages:
            self.group_messages[group_id] = []
        
        # 初始化最近复读内容
        if group_id not in self.last_repeated_content:
            self.last_repeated_content[group_id] = {'content': '', 'timestamp': None}
        
        # 添加新消息到记录，包含时间戳和内容
        self.group_messages[group_id].append({
            'time': current_time,
            'content': message_content
        })
        
        # 过滤出时间窗口内的消息
        time_window_seconds = time_window_minutes * 60
        filtered_messages = []
        for msg in reversed(self.group_messages[group_id]):
            time_diff = (current_time - msg['time']).total_seconds()
            if time_diff <= time_window_seconds:
                filtered_messages.append(msg)
            else:
                break  # 因为消息是按时间顺序添加的，后面的消息时间更旧，所以可以直接跳出循环
        
        # 只保留时间窗口内的消息，反转回原始顺序
        self.group_messages[group_id] = filtered_messages[::-1]
        
        # 限制消息数量窗口，只保留最近的message_window_size条消息
        if len(self.group_messages[group_id]) > message_window_size:
            self.group_messages[group_id] = self.group_messages[group_id][-message_window_size:]
        
        # 统计当前消息在窗口内出现的次数
        same_count = 0
        for msg in self.group_messages[group_id]:
            if msg['content'] == message_content:
                same_count += 1
        
        # 检查是否满足复读条件：z条相同消息，且不是在冷却时间内已经复读过的内容
        can_repeat = False
        if same_count >= required_same_count:
            # 检查是否在冷却时间内
            if message_content != self.last_repeated_content[group_id]['content']:
                can_repeat = True
            else:
                # 同一内容，检查是否超过冷却时间
                last_repeat_time = self.last_repeated_content[group_id]['timestamp']
                if last_repeat_time is None:
                    can_repeat = True
                else:
                    time_diff = (current_time - last_repeat_time).total_seconds()
                    if time_diff > repeat_cooldown_minutes * 60:
                        can_repeat = True
        
        if can_repeat:
            # 执行复读
            await self.send_text(group_id, message_content)
            
            # 记录最近复读的内容和时间，避免重复复读
            self.last_repeated_content[group_id] = {
                'content': message_content,
                'timestamp': current_time
            }
        
        return True, True, None, None, None


@register_plugin
class RepeatSameContentPlugin(BasePlugin):
    """
    连续相同内容复读插件
    """
    
    # 插件基本信息
    plugin_name: str = "repeat_same_content_plugin"
    enable_plugin: bool = False
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"
    
    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本信息",
        "repeat": "复读功能配置"
    }
    
    # 配置Schema定义
    config_schema: dict = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
        },
        "repeat": {
            "time_window_minutes": ConfigField(
                type=int, default=5, description="时间窗口x：在x分钟内"
            ),
            "message_window_size": ConfigField(
                type=int, default=10, description="消息数量窗口y：在y条消息内"
            ),
            "required_same_count": ConfigField(
                type=int, default=3, description="相同消息数量z：检测到z条相同消息则触发复读"
            ),
            "max_message_length": ConfigField(
                type=int, default=100, description="最大消息长度限制，超过则不处理"
            ),
            "repeat_cooldown_minutes": ConfigField(
                type=int, default=10, description="同一内容复读冷却时间（分钟），在冷却时间内同一内容不会重复复读"
            ),
        },
    }
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        from src.plugin_system.base.component_types import ComponentInfo
        return [
            (RepeatSameContentHandler.get_handler_info(), RepeatSameContentHandler),
        ]
