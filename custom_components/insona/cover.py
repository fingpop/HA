"""inSona网关窗帘控制平台。"""
import logging
from typing import Any, Optional

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DEVICE_TYPE_COVER,
    FUNC_ONOFF,
)
from .gateway import InSonaGateway

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置inSona网关窗帘实体。"""
    gateway = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    
    # 查找所有窗帘设备
    for did, device in gateway.devices.items():
        if device["type"] == DEVICE_TYPE_COVER:
            entities.append(InSonaCover(gateway, device))
    
    if entities:
        async_add_entities(entities)

class InSonaCover(CoverEntity):
    """inSona窗帘实体。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona窗帘。"""
        self.gateway = gateway
        self.device = device
        self.did = device["did"]
        self._attr_unique_id = f"{DOMAIN}_{self.did}"
        self._attr_name = device["name"]
        self._attr_device_class = CoverDeviceClass.CURTAIN
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | 
            CoverEntityFeature.CLOSE | 
            CoverEntityFeature.SET_POSITION |
            CoverEntityFeature.STOP
        )
        
        # 设备信息
        room_id = device.get("roomId")
        room_name = gateway.rooms.get(room_id, "")
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.did)},
            name=self.name,
            manufacturer="inSona",
            model=f"Type {device['type']} (PID {device['pid']})",
            via_device=(DOMAIN, f"{gateway.host}:{gateway.port}"),
            suggested_area=room_name,
        )
        
        # 注册状态更新回调
        self._remove_status_listener = gateway.register_status_listener(
            self.did, self._handle_status_update
        )
        
        # 注册断开连接回调
        self._remove_disconnect_listener = gateway.register_disconnect_callback(
            self._handle_disconnect
        )
    
    @callback
    def _handle_status_update(self) -> None:
        """处理设备状态更新。"""
        self.async_write_ha_state()
    
    @callback
    def _handle_disconnect(self) -> None:
        """处理网关断开连接。"""
        self.async_write_ha_state()
        
    async def async_will_remove_from_hass(self) -> None:
        """实体从HomeAssistant移除时调用。"""
        self._remove_status_listener()
        self._remove_disconnect_listener()
    
    @property
    def available(self) -> bool:
        """设备是否可用。"""
        return self.gateway.connected and self.device.get("alive", 0) == 1
    
    @property
    def is_closed(self) -> Optional[bool]:
        """窗帘是否关闭。"""
        # 检查 func=2, value=[0] 的情况，表示窗帘关闭
        if self.device.get("func") == FUNC_ONOFF and len(self.device["value"]) > 0 and self.device["value"][0] == 0:
            return True
        
        # 根据位置判断是否关闭 (0表示全关，100表示全开)
        if len(self.device["value"]) > 1:
            return self.device["value"][1] == 0
        
        return None
    
    @property
    def current_cover_position(self) -> Optional[int]:
        """获取窗帘当前位置。"""
        # 检查 func=2, value=[0] 的情况，表示窗帘关闭，位置为0
        if self.device.get("func") == FUNC_ONOFF and len(self.device["value"]) > 0 and self.device["value"][0] == 0:
            return 0
        
        # 窗帘位置为 0-100，0 表示全关，100 表示全开
        if len(self.device["value"]) > 1:
            return self.device["value"][1]
        
        return None
    
    async def async_open_cover(self, **kwargs: Any) -> None:
        """打开窗帘。"""
        await self.gateway.control_device(self.did, "level", [100])
    
    async def async_close_cover(self, **kwargs: Any) -> None:
        """关闭窗帘。"""
        await self.gateway.control_device(self.did, "level", [0])
    
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """停止窗帘。"""
        # 发送停止命令，保持当前位置
        if len(self.device["value"]) > 1:
            current_position = self.device["value"][1]
            await self.gateway.control_device(self.did, "curtainstop", [current_position])
    
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """设置窗帘位置。"""
        position = kwargs.get("position", 0)
        await self.gateway.control_device(self.did, "level", [position]) 