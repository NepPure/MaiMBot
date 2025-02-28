import customtkinter as ctk
from typing import Dict, List
import json
from datetime import datetime
import time
import threading
import queue
import sys
import os

from pymongo import MongoClient
from typing import Optional

class Database:
    _instance: Optional["Database"] = None
    
    def __init__(self, host: str, port: int, db_name: str):
        self.client = MongoClient(host, port)
        self.db = self.client[db_name]
        
    @classmethod
    def initialize(cls, host: str, port: int, db_name: str) -> "Database":
        if cls._instance is None:
            cls._instance = cls(host, port, db_name)
        return cls._instance
        
    @classmethod
    def get_instance(cls) -> "Database":
        if cls._instance is None:
            raise RuntimeError("Database not initialized")
        return cls._instance 
    


class ReasoningGUI:
    def __init__(self):
        # 记录启动时间戳，转换为Unix时间戳
        self.start_timestamp = datetime.now().timestamp()
        print(f"程序启动时间戳: {self.start_timestamp}")
        
        # 设置主题
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # 创建主窗口
        self.root = ctk.CTk()
        self.root.title('爱酱推理')
        self.root.geometry('800x600')
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # 初始化数据库连接
        try:
            self.db = Database.get_instance().db
            print("数据库连接成功")
        except RuntimeError:
            print("数据库未初始化，正在尝试初始化...")
            try:
                Database.initialize("localhost", 27017, "maimai_bot")
                self.db = Database.get_instance().db
                print("数据库初始化成功")
            except Exception as e:
                print(f"数据库初始化失败: {e}")
                sys.exit(1)
        
        # 存储群组数据
        self.group_data: Dict[str, List[dict]] = {}
        
        # 创建更新队列
        self.update_queue = queue.Queue()
        
        # 创建主框架
        self.frame = ctk.CTkFrame(self.root)
        self.frame.pack(pady=20, padx=20, fill="both", expand=True)
        
        # 添加标题
        self.title = ctk.CTkLabel(self.frame, text="AI推理监控系统", font=("Arial", 24))
        self.title.pack(pady=10, padx=10)
        
        # 创建左右分栏
        self.paned = ctk.CTkFrame(self.frame)
        self.paned.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 左侧群组列表
        self.left_frame = ctk.CTkFrame(self.paned, width=200)
        self.left_frame.pack(side="left", fill="y", padx=5, pady=5)
        
        self.group_label = ctk.CTkLabel(self.left_frame, text="群组列表", font=("Arial", 16))
        self.group_label.pack(pady=5)
        
        self.group_listbox = ctk.CTkTextbox(self.left_frame, width=180, height=400)
        self.group_listbox.pack(pady=5, padx=5)
        
        # 右侧内容显示
        self.right_frame = ctk.CTkFrame(self.paned)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        self.content_label = ctk.CTkLabel(self.right_frame, text="推理内容", font=("Arial", 16))
        self.content_label.pack(pady=5)
        
        # 创建富文本显示框
        self.content_text = ctk.CTkTextbox(self.right_frame, width=500, height=400)
        self.content_text.pack(pady=5, padx=5, fill="both", expand=True)
        
        # 配置文本标签 - 只使用颜色
        self.content_text.tag_config("timestamp", foreground="#888888")  # 时间戳使用灰色
        self.content_text.tag_config("user", foreground="#4CAF50")  # 用户名使用绿色
        self.content_text.tag_config("message", foreground="#2196F3")  # 消息使用蓝色
        self.content_text.tag_config("model", foreground="#9C27B0")  # 模型名称使用紫色
        self.content_text.tag_config("reasoning", foreground="#FF9800")  # 推理过程使用橙色
        self.content_text.tag_config("response", foreground="#E91E63")  # 回复使用粉色
        self.content_text.tag_config("separator", foreground="#666666")  # 分隔符使用深灰色
        
        # 底部控制栏
        self.control_frame = ctk.CTkFrame(self.frame)
        self.control_frame.pack(fill="x", padx=10, pady=5)
        
        self.clear_button = ctk.CTkButton(
            self.control_frame,
            text="清除显示",
            command=self.clear_display,
            width=120
        )
        self.clear_button.pack(side="left", padx=5)
        
        # 添加群组点击事件
        self.group_listbox.bind('<Button-1>', self._on_group_click)
        
        # 启动自动更新线程
        self.update_thread = threading.Thread(target=self._auto_update, daemon=True)
        self.update_thread.start()
        
        # 启动GUI更新检查
        self.root.after(100, self._process_queue)
    
    def _on_closing(self):
        """处理窗口关闭事件"""
        self.root.quit()
        sys.exit(0)
    
    def _process_queue(self):
        """处理更新队列中的任务"""
        try:
            while True:
                task = self.update_queue.get_nowait()
                if task['type'] == 'update_group_list':
                    self._update_group_list_gui()
                elif task['type'] == 'update_display':
                    self._update_display_gui(task['group_id'])
        except queue.Empty:
            pass
        finally:
            # 继续检查队列
            self.root.after(100, self._process_queue)
    
    def _update_group_list_gui(self):
        """在主线程中更新群组列表"""
        self.group_listbox.delete("1.0", "end")
        for group_id in self.group_data.keys():
            self.group_listbox.insert("end", f"群号: {group_id}\n")
    
    def _update_display_gui(self, group_id: str):
        """在主线程中更新显示内容"""
        if group_id in self.group_data:
            self.content_text.delete("1.0", "end")
            for item in self.group_data[group_id]:
                # 时间戳
                time_str = item['time'].strftime("%Y-%m-%d %H:%M:%S")
                self.content_text.insert("end", f"[{time_str}]\n", "timestamp")
                
                # 用户信息
                self.content_text.insert("end", "用户: ", "timestamp")
                self.content_text.insert("end", f"{item.get('user', '未知')}\n", "user")
                
                # 消息内容
                self.content_text.insert("end", "消息: ", "timestamp")
                self.content_text.insert("end", f"{item.get('message', '')}\n", "message")
                
                # 模型信息
                self.content_text.insert("end", "模型: ", "timestamp")
                self.content_text.insert("end", f"{item.get('model', '')}\n", "model")
                
                # 推理过程
                self.content_text.insert("end", "推理过程:\n", "timestamp")
                reasoning_text = item.get('reasoning', '')
                # 处理推理过程中的Markdown格式
                lines = reasoning_text.split('\n')
                for line in lines:
                    if line.strip():
                        # 添加缩进
                        self.content_text.insert("end", "    " + line + "\n", "reasoning")
                
                # 回复内容
                self.content_text.insert("end", "回复: ", "timestamp")
                self.content_text.insert("end", f"{item.get('response', '')}\n", "response")
                
                # 分隔符
                self.content_text.insert("end", f"\n{'='*50}\n\n", "separator")
                
            # 滚动到顶部
            self.content_text.see("1.0")
    
    def _auto_update(self):
        """自动更新函数"""
        while True:
            try:
                # 从数据库获取最新数据，只获取启动时间之后的记录
                query = {"time": {"$gt": self.start_timestamp}}
                print(f"查询条件: {query}")
                
                # 先获取一条记录检查时间格式
                sample = self.db.reasoning_logs.find_one()
                if sample:
                    print(f"样本记录时间格式: {type(sample['time'])} 值: {sample['time']}")
                
                cursor = self.db.reasoning_logs.find(query).sort("time", -1)
                new_data = {}
                total_count = 0
                
                for item in cursor:
                    # 调试输出
                    if total_count == 0:
                        print(f"记录时间: {item['time']}, 类型: {type(item['time'])}")
                    
                    total_count += 1
                    group_id = str(item.get('group_id', 'unknown'))
                    if group_id not in new_data:
                        new_data[group_id] = []
                    
                    # 转换时间戳为datetime对象
                    if isinstance(item['time'], (int, float)):
                        time_obj = datetime.fromtimestamp(item['time'])
                    elif isinstance(item['time'], datetime):
                        time_obj = item['time']
                    else:
                        print(f"未知的时间格式: {type(item['time'])}")
                        time_obj = datetime.now()  # 使用当前时间作为后备
                    
                    new_data[group_id].append({
                        'time': time_obj,
                        'user': item.get('user_nickname', item.get('user_id', '未知')),
                        'message': item.get('message', ''),
                        'model': item.get('model', '未知'),
                        'reasoning': item.get('reasoning', ''),
                        'response': item.get('response', ''),
                    })
                
                print(f"从数据库加载了 {total_count} 条记录，分布在 {len(new_data)} 个群组中")
                
                # 更新数据
                if new_data != self.group_data:
                    self.group_data = new_data
                    print("数据已更新，正在刷新显示...")
                    # 将更新任务添加到队列
                    self.update_queue.put({'type': 'update_group_list'})
                    if self.group_data:
                        latest_group = next(iter(self.group_data))
                        self.update_queue.put({
                            'type': 'update_display',
                            'group_id': latest_group
                        })
            except Exception as e:
                print(f"自动更新出错: {e}")
            
            # 每5秒更新一次
            time.sleep(5)
    
    def _on_group_click(self, event):
        """处理群组点击事件"""
        try:
            # 获取点击位置的文本行
            index = self.group_listbox.index(f"@{event.x},{event.y}")
            line = self.group_listbox.get(f"{index} linestart", f"{index} lineend")
            if line.startswith("群号: "):
                group_id = line.replace("群号: ", "").strip()
                self.update_display(group_id)
        except Exception as e:
            print(f"处理群组点击事件出错: {e}")
    
    def update_display(self, group_id: str):
        """更新显示指定群组的内容"""
        if group_id in self.group_data:
            self.content_text.delete("1.0", "end")
            for item in self.group_data[group_id]:
                # 时间戳
                time_str = item['time'].strftime("%Y-%m-%d %H:%M:%S")
                self.content_text.insert("end", f"[{time_str}]\n", "timestamp")
                
                # 用户信息
                self.content_text.insert("end", "用户: ", "timestamp")
                self.content_text.insert("end", f"** {item.get('user', '未知')} **\n", "user")
                
                # 消息内容
                self.content_text.insert("end", "消息: ", "timestamp")
                self.content_text.insert("end", f"{item.get('message', '')}\n", "message")
                
                # 模型信息
                self.content_text.insert("end", "模型: ", "timestamp")
                self.content_text.insert("end", f"{item.get('model', '')}\n", "model")
                
                # 推理过程
                self.content_text.insert("end", "推理过程:\n", "timestamp")
                reasoning_text = item.get('reasoning', '')
                # 处理推理过程中的Markdown格式
                lines = reasoning_text.split('\n')
                for line in lines:
                    if line.strip():
                        # 添加缩进
                        self.content_text.insert("end", "    " + line + "\n", "reasoning")
                
                # 回复内容
                self.content_text.insert("end", "回复: ", "timestamp")
                self.content_text.insert("end", f"{item.get('response', '')}\n", "response")
                
                # 分隔符
                self.content_text.insert("end", f"\n{'='*50}\n\n", "separator")
                
            # 滚动到顶部
            self.content_text.see("1.0")
    
    def clear_display(self):
        """清除显示内容"""
        self.content_text.delete("1.0", "end")
    
    def run(self):
        """运行GUI"""
        self.root.mainloop()


def main():
    """主函数"""
    Database.initialize(
        "127.0.0.1",
        27017,
        "MegBot"
    )
    
    app = ReasoningGUI()
    app.run()



if __name__ == "__main__":
    main()
