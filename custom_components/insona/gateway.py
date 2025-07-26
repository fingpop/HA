"""inSona网关通信类。"""
import asyncio
import json
import logging
import random
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from homeassistant.core import HomeAssistant, callback

from .const import (
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_COVER,
    DEVICE_TYPE_PANEL,
    DEVICE_TYPE_SENSOR,
    FUNC_ONOFF,
    FUNC_BRIGHTNESS,
    FUNC_CTL,
    FUNC_HSL,
    FUNC_PANEL,
    ACTION_ONOFF,
    ACTION_LEVEL,
    ACTION_CTL,
    ACTION_HSL,
)

# 场景相关常量
SCENE_ACTION = "scene"

_LOGGER = logging.getLogger(__name__)

class InSonaGateway:
    """inSona网关通信类。"""

    def __init__(self, hass: HomeAssistant, host: str, port: int):
        """初始化inSona网关。"""
        self.hass = hass
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False
        
        self.devices = {}
        self.rooms = {}
        self.scenes = {}  # 添加场景列表
        self.status_listeners = {}
        self._disconnect_callbacks = set()
        self._read_task = None
        self._event_task = None
        self._response_queue = asyncio.Queue()  # 添加响应队列
        self._waiting_commands = {}  # 存储等待响应的命令
        
    async def connect(self) -> None:
        """连接到inSona网关。"""
        if self.connected:
            return
            
        try:
            # 增加缓冲区大小到 1MB
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port, limit=1024*1024
            )
            self.connected = True
            
            # 先启动读取任务，再启动事件处理任务
            self._read_task = asyncio.create_task(self._read_data_task())
            self._event_task = asyncio.create_task(self._event_listener())
            
            _LOGGER.info("已连接到inSona网关 %s:%s", self.host, self.port)
        except Exception as err:
            self.connected = False
            _LOGGER.error("连接到inSona网关失败: %s", err)
            raise
    
    async def disconnect(self) -> None:
        """断开连接。"""
        if not self.connected:
            return
            
        self.connected = False
        
        # 先取消读取任务
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        
        # 再取消事件任务
        if self._event_task is not None:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
            self._event_task = None
        
        if self.writer is not None:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
            self.reader = None
        
        _LOGGER.info("已断开与inSona网关的连接")
        
        # 调用所有断开回调
        for callback_func in self._disconnect_callbacks:
            callback_func()
    
    def register_disconnect_callback(self, callback_func: Callable[[], None]) -> Callable[[], None]:
        """注册断开连接的回调函数。"""
        self._disconnect_callbacks.add(callback_func)
        
        def remove_callback() -> None:
            self._disconnect_callbacks.remove(callback_func)
            
        return remove_callback
    
    async def _send_command(self, command: dict) -> None:
        """发送命令到网关。"""
        if not self.connected:
            await self.connect()
            
        cmd_str = json.dumps(command) + "\r\n"
        self.writer.write(cmd_str.encode("utf-8"))
        await self.writer.drain()
    
    async def _read_data_task(self) -> None:
        """持续读取网关数据的任务。"""
        while self.connected and self.reader is not None:
            try:
                data = await self.reader.readuntil(b"\r\n")
                response = json.loads(data.decode("utf-8"))
                
                # 将响应放入队列
                await self._response_queue.put(response)
            except asyncio.LimitOverrunError as err:
                _LOGGER.error("读取数据超出缓冲区限制: %s", err)
                # 尝试读取剩余数据以清空缓冲区
                try:
                    await self.reader.readexactly(err.consumed)
                except Exception as e:
                    _LOGGER.error("清空缓冲区时出错: %s", e)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("读取数据出错: %s", err)
                await asyncio.sleep(1)
                
                # 检查连接状态
                if self.connected and (self.reader is None or self.reader.at_eof()):
                    self.connected = False
                    
                    # 通知断开连接
                    for callback_func in self._disconnect_callbacks:
                        callback_func()
                    
                    # 尝试重新连接
                    try:
                        await self.connect()
                    except Exception as conn_err:
                        _LOGGER.error("重新连接失败: %s", conn_err)
    
    async def _wait_for_specific_response(self, method: str, uuid: int, timeout: float = 10.0) -> Optional[dict]:
        """等待特定的响应。"""
        future = asyncio.Future()
        self._waiting_commands[uuid] = (method, future)
        
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            _LOGGER.error("等待 %s 响应超时 (uuid: %s)", method, uuid)
            return None
        finally:
            self._waiting_commands.pop(uuid, None)
    
    async def _event_listener(self) -> None:
        """处理从队列中获取的响应。"""
        while self.connected:
            try:
                # 从队列获取响应
                response = await self._response_queue.get()
                method = response.get("method", "")
                uuid = response.get("uuid")
                
                # 处理s.query方法的响应，用于初始化设备和房间信息
                _LOGGER.debug("收到s.query响应: %s", response)
                if method == "s.query" and response.get("result") == "ok":
                    # 解析房间信息
                    for room in response.get("rooms", []):
                        self.rooms[room["roomId"]] = room["name"]
                    
                    # 解析设备信息
                    for device in response.get("devices", []):
                        # 根据设备类型和func初始化value数组
                        func = device.get("func", 0)
                        funcs = device.get("funcs", [])
                        
                        # 确保value数组长度足够
                        if func == FUNC_ONOFF:  # 开关功能
                            if len(device.get("value", [])) < 1:
                                device["value"] = [0]
                        elif func == FUNC_BRIGHTNESS:  # 亮度功能
                            if len(device.get("value", [])) < 2:
                                device["value"] = [0, 0]
                        elif func == FUNC_CTL:  # 亮度色温功能
                            if len(device.get("value", [])) < 3:
                                device["value"] = [0, 0, 50]
                        elif func == FUNC_HSL:  # HSL功能
                            if len(device.get("value", [])) < 4:
                                device["value"] = [0, 0, 0, 100]
                        
                        self.devices[device["did"]] = device
                    
                    # 解析场景信息
                    for scene in response.get("scenes", []):
                        self.scenes[scene["sceneId"]] = scene["name"]
                    
                    # 处理等待中的命令响应
                    if uuid in self._waiting_commands:
                        expected_method, future = self._waiting_commands[uuid]
                        if method == expected_method and not future.done():
                            future.set_result(response)
                
                # 处理等待中的命令响应
                elif uuid in self._waiting_commands:
                    expected_method, future = self._waiting_commands[uuid]
                    if method == expected_method and not future.done():
                        _LOGGER.debug("设置等待命令的结果: uuid=%s, method=%s, response=%s", uuid, method, response)
                        future.set_result(response)
                
                # 处理状态事件
                elif method == "s.event" and response.get("evt") == "status":
                    did = response.get("did")
                    func = response.get("func")
                    value = response.get("value", [])
                    status = response.get("status")
                    
                    _LOGGER.debug(
                        "收到状态更新: did=%s, func=%s, value=%s, status=%s",
                        did, func, value, status
                    )
                
                # 处理meshchange事件，主动同步网关数据
                elif method == "s.event" and response.get("evt") == "meshchange":
                    _LOGGER.info("收到meshchange事件，主动同步网关数据")
                    # 在后台任务中执行查询，避免阻塞事件循环
                    asyncio.create_task(self.query_devices())
                    
                    # 更新设备状态
                    if did in self.devices:
                        device = self.devices[did]
                        
                        # 处理灯光设备状态更新
                        if device["type"] == DEVICE_TYPE_LIGHT:
                            # 更新当前func，这对于双模式灯具特别重要
                            device["func"] = func
                            
                            # 根据不同func处理状态
                            if func == FUNC_ONOFF:  # 开关控制
                                if value and len(value) > 0:
                                    device["value"][0] = value[0]  # 更新开关状态
                                    
                                    # 当灯打开时，如果有status信息，需要根据status[0]更新模式和值
                                    if value[0] == 1 and status:
                                        mode = status[0]
                                        if mode == 3:  # 亮度模式
                                            device["func"] = FUNC_BRIGHTNESS
                                            if len(device["value"]) < 2:
                                                device["value"].append(0)
                                            device["value"][1] = status[1]  # 亮度值
                                        
                                        elif mode == 4:  # 亮度色温模式
                                            device["func"] = FUNC_CTL
                                            while len(device["value"]) < 3:
                                                device["value"].append(0)
                                            device["value"][1] = status[1]  # 亮度值
                                            device["value"][2] = status[2]  # 色温值
                                        
                                        elif mode == 5:  # HSL模式
                                            device["func"] = FUNC_HSL
                                            while len(device["value"]) < 4:
                                                device["value"].append(0)
                                            device["value"][1] = status[1]  # 亮度值
                                            device["value"][2] = status[2]  # hue值
                                            device["value"][3] = status[3]  # 饱和度值
                            
                            elif func == FUNC_BRIGHTNESS:  # 亮度控制
                                device["func"] = FUNC_BRIGHTNESS
                                device["value"][0] = 1  # 设置为开启状态
                                if value and len(value) > 0:
                                    device["value"][1] = value[0]  # 更新亮度值（第一个值为亮度）
                            
                            elif func == FUNC_CTL:  # 色温控制
                                # 确保value列表长度足够
                                while len(device["value"]) < 3:
                                    device["value"].append(0)
                                
                                device["value"][0] = 1  # 设置为开启状态
                                if value:
                                    if len(value) > 0:
                                        device["value"][1] = value[0]  # 亮度
                                    if len(value) > 1:
                                        device["value"][2] = value[1]  # 色温
                            
                            elif func == FUNC_HSL:  # HSL控制
                                device["func"] = FUNC_HSL
                                # 确保 value 列表有足够长度
                                while len(device["value"]) < 4:
                                    device["value"].append(0)
                                    
                                device["value"][0] = 1  # 设置为开启状态
                                if value:
                                    if len(value) > 0:
                                        device["value"][1] = value[0]  # 亮度
                                    if len(value) > 1:
                                        device["value"][2] = value[1]  # hue
                                    if len(value) > 2:
                                        device["value"][3] = value[2]  # 饱和度
                        
                        # 处理窗帘类型设备
                        elif device["type"] == DEVICE_TYPE_COVER:
                            if func == FUNC_ONOFF:  # func=2 开关控制
                                # 确保 value 列表有足够长度
                                while len(device["value"]) < 2:
                                    device["value"].append(0)
                                    
                                if value and len(value) > 0:
                                    device["func"] = func
                                    device["value"][0] = value[0]  # 更新开关状态 0=关闭 1=打开
                                    
                                    # 当收到 func=2, value=[0] 时，窗帘位置设置为0（全关）
                                    if value[0] == 0:
                                        device["value"][1] = 0
                            elif func == 3:  # level控制
                                # 确保 value 列表有足够长度
                                while len(device["value"]) < 2:
                                    device["value"].append(0)
                                    
                                device["func"] = func
                                device["value"][0] = 1  # 设置为开启状态
                                if value and len(value) > 0:
                                    device["value"][1] = value[0]  # 更新位置值
                        
                        # 调用状态更新回调
                        if did in self.status_listeners:
                            for callback_func in self.status_listeners[did]:
                                callback_func()
                
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("事件处理出错: %s", err)
                await asyncio.sleep(0.1)
    
    def register_status_listener(self, did: str, callback_func: Callable[[], None]) -> Callable[[], None]:
        """注册设备状态更新的回调函数。"""
        if did not in self.status_listeners:
            self.status_listeners[did] = set()
            
        self.status_listeners[did].add(callback_func)
        
        def remove_callback() -> None:
            if did in self.status_listeners:
                self.status_listeners[did].remove(callback_func)
                if not self.status_listeners[did]:
                    del self.status_listeners[did]
                
        return remove_callback
    
    async def query_devices(self) -> None:
        """查询所有设备和房间信息。"""
        uuid = random.randint(1000, 9999)
        command = {
            "version": 1,
            "uuid": uuid,
            "method": "c.query",
            "type": "all"
        }
        
        # 发送命令
        await self._send_command(command)
        
        # 等待响应
        response = await self._wait_for_specific_response("s.query", uuid)
        
        if response and response.get("result") == "ok":
            _LOGGER.info("成功获取到 %d 个设备和 %d 个房间", 
                         len(self.devices), len(self.rooms))
        else:
            _LOGGER.error("查询设备失败: %s", response)
            raise Exception("查询设备失败")
    
    async def control_device(self, did: str, action: str, value: List[int], transition: int = 0) -> bool:
        """控制设备。"""
        if did not in self.devices:
            _LOGGER.error("设备 %s 不存在", did)
            return False
            
        command = {
            "version": 1,
            "uuid": random.randint(1000, 9999),
            "method": "c.control",
            "did": did,
            "action": action,
            "value": value,
            "transition": transition
        }
        
        try:
            await self._send_command(command)
            return True
        except Exception as err:
            _LOGGER.error("控制设备失败: %s", err)
            return False
    
    async def query_scenes(self) -> None:
        """查询场景列表。"""
        uuid = random.randint(1000, 9999)
        command = {
            "version": 1,
            "uuid": uuid,
            "method": "c.query.scene"
        }
        
        # 发送命令
        _LOGGER.debug("发送查询场景指令: %s", command)
        await self._send_command(command)
        
        # 等待响应
        response = await self._wait_for_specific_response("s.query.scene", uuid, 15.0)  # 增加超时时间到15秒
        _LOGGER.debug("收到查询场景响应: %s", response)
        
        # 检查响应是否为空
        if response is None:
            _LOGGER.error("查询场景失败: 收到空响应")
            raise Exception("查询场景失败: 收到空响应")
        
        # 检查响应是否包含错误信息
        if "error" in response:
            _LOGGER.error("查询场景失败: 网关返回错误: %s", response["error"])
            raise Exception(f"查询场景失败: 网关返回错误: {response['error']}")
        
        # 检查响应方法是否正确
        if response.get("method") != "s.query.scene":
            _LOGGER.error("查询场景失败: 收到意外的响应方法: %s", response.get("method"))
            raise Exception(f"查询场景失败: 收到意外的响应方法: {response.get('method')}")
        
        # 解析场景信息
        scenes = response.get("scenes", [])
        if not scenes:
            _LOGGER.warning("未获取到任何场景信息")
        else:
            for scene in scenes:
                self.scenes[scene["sceneId"]] = scene["name"]
            _LOGGER.info("成功获取到 %d 个场景", len(self.scenes))
    
    async def activate_scene(self, scene_id: int) -> bool:
        """激活场景。"""
        command = {
            "version": 1,
            "uuid": random.randint(1000, 9999),
            "method": "c.control",
            "action": SCENE_ACTION,
            "value": [str(scene_id)],
            "transition": 0
        }
        
        try:
            await self._send_command(command)
            return True
        except Exception as err:
            _LOGGER.error("激活场景失败: %s", err)
            return False