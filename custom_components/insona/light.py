"""inSona网关灯光控制平台。"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.color import (
    color_hsv_to_RGB,
    color_RGB_to_hsv,
)

from .const import (
    DOMAIN,
    DEVICE_TYPE_LIGHT,
    FUNC_ONOFF,
    FUNC_BRIGHTNESS,
    FUNC_CTL,
    FUNC_HSL,
    ACTION_ONOFF,
    ACTION_LEVEL,
    ACTION_CTL,
    ACTION_HSL,
)
from .gateway import InSonaGateway

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置inSona网关灯光实体。"""
    gateway = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    
    # 查找所有灯光设备
    for did, device in gateway.devices.items():
        if device["type"] == DEVICE_TYPE_LIGHT:
            funcs = device.get("funcs", [])
            
            # 检查是否为双模式灯具（同时支持色温和RGB）
            if FUNC_CTL in funcs and FUNC_HSL in funcs:
                entities.append(InSonaDualModeLight(gateway, device))
            elif FUNC_HSL in funcs:
                entities.append(InSonaRGBLight(gateway, device))
            elif FUNC_CTL in funcs:
                entities.append(InSonaColorTempLight(gateway, device))
            elif FUNC_BRIGHTNESS in funcs:
                entities.append(InSonaDimmableLight(gateway, device))
            elif FUNC_ONOFF in funcs:
                entities.append(InSonaLight(gateway, device))
    
    if entities:
        async_add_entities(entities)

class InSonaLightBase(LightEntity):
    """inSona灯光基础类。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona灯光。"""
        self.gateway = gateway
        self.device = device
        self.did = device["did"]
        self._attr_unique_id = f"{DOMAIN}_{self.did}"
        self._attr_name = device["name"]
        
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
    def is_on(self) -> bool:
        """灯是否打开。"""
        return self.device["value"][0] == 1
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """打开灯。"""
        await self.gateway.control_device(self.did, ACTION_ONOFF, [1])
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """关闭灯。"""
        await self.gateway.control_device(self.did, ACTION_ONOFF, [0])

class InSonaLight(InSonaLightBase):
    """inSona开关灯。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona开关灯。"""
        super().__init__(gateway, device)
        self._attr_color_mode = ColorMode.ONOFF
        self._attr_supported_color_modes = {ColorMode.ONOFF}

class InSonaDimmableLight(InSonaLightBase):
    """inSona可调光灯。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona可调光灯。"""
        super().__init__(gateway, device)
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    
    @property
    def brightness(self) -> Optional[int]:
        """获取灯的亮度。"""
        if len(self.device["value"]) > 1:
            return int(self.device["value"][1] * 255 / 100)
        return None
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """打开灯，设置亮度。"""
        if ATTR_BRIGHTNESS in kwargs:
            brightness = int(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            transition = kwargs.get(ATTR_TRANSITION, 0)
            # 修改：仅发送亮度值，不包含开关状态
            await self.gateway.control_device(self.did, ACTION_LEVEL, [brightness], transition)
        else:
            await super().async_turn_on(**kwargs)

class InSonaColorTempLight(InSonaDimmableLight):
    """inSona色温灯。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona色温灯。"""
        super().__init__(gateway, device)
        self._attr_color_mode = ColorMode.COLOR_TEMP
        self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
        self._attr_min_color_temp_kelvin = 2700  # 最低色温 2700K (最暖)
        self._attr_max_color_temp_kelvin = 6500  # 最高色温 6500K (最冷)
    
    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """获取灯的色温（开尔文温度）。"""
        if len(self.device["value"]) > 2:
            # 将设备的色温值(0-100)转换为开尔文温度(2700K-6500K)
            # inSona: 0(最暖) -> 100(最冷)
            # HomeAssistant: 2700K(最暖) -> 6500K(最冷)
            ct_device_value = self.device["value"][2]
            # 正确映射: 0 -> 2700K, 100 -> 6500K
            kelvin = self.min_color_temp_kelvin + (ct_device_value / 100) * (self.max_color_temp_kelvin - self.min_color_temp_kelvin)
            return int(kelvin)
        return None
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """打开灯，设置亮度和色温。"""
        if ATTR_COLOR_TEMP_KELVIN in kwargs or ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs.get(
                ATTR_BRIGHTNESS, 
                int(self.device["value"][1] * 255 / 100) if len(self.device["value"]) > 1 else 255
            )
            brightness = int(brightness * 100 / 255)
            
            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                # 将开尔文色温转换为设备值(0-100)
                kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
                # 确保在允许范围内
                kelvin = max(self.min_color_temp_kelvin, min(self.max_color_temp_kelvin, kelvin))
                # 正确映射: 2700K -> 0, 6500K -> 100
                ct_device_value = int((kelvin - self.min_color_temp_kelvin) / (self.max_color_temp_kelvin - self.min_color_temp_kelvin) * 100)
            else:
                ct_device_value = self.device["value"][2] if len(self.device["value"]) > 2 else 50
            
            transition = kwargs.get(ATTR_TRANSITION, 0)
            # 发送亮度和色温值
            await self.gateway.control_device(self.did, ACTION_CTL, [brightness, ct_device_value], transition)
        else:
            await super().async_turn_on(**kwargs)

class InSonaRGBLight(InSonaLightBase):
    """inSona RGB灯。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona RGB灯。"""
        super().__init__(gateway, device)
        self._attr_color_mode = ColorMode.HS
        self._attr_supported_color_modes = {ColorMode.HS}
        self._attr_supported_features = LightEntityFeature.TRANSITION
    
    @property
    def brightness(self) -> Optional[int]:
        """获取灯的亮度。"""
        if len(self.device["value"]) > 1:
            return int(self.device["value"][1] * 255 / 100)
        return None
    
    @property
    def hs_color(self) -> Optional[Tuple[float, float]]:
        """获取灯的HSL颜色。"""
        if len(self.device["value"]) > 3:
            hue = self.device["value"][2]  # hue值(0-360)
            saturation = self.device["value"][3]  # 饱和度(0-100)
            return (hue, saturation)
        return None
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """打开灯，设置亮度和颜色。"""
        if ATTR_HS_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs.get(
                ATTR_BRIGHTNESS, 
                int(self.device["value"][1] * 255 / 100) if len(self.device["value"]) > 1 else 255
            )
            brightness = int(brightness * 100 / 255)
            
            if ATTR_HS_COLOR in kwargs:
                hue, saturation = kwargs[ATTR_HS_COLOR]
                hue = int(hue)  # hue值(0-360)
                saturation = int(saturation)  # 饱和度(0-100)
            else:
                hue = self.device["value"][2] if len(self.device["value"]) > 2 else 0
                saturation = self.device["value"][3] if len(self.device["value"]) > 3 else 100
            
            transition = kwargs.get(ATTR_TRANSITION, 0)
            # 修改：仅发送亮度、色调和饱和度，不包含开关状态
            await self.gateway.control_device(self.did, ACTION_HSL, [brightness, hue, saturation], transition)
        else:
            await super().async_turn_on(**kwargs)

class InSonaDualModeLight(InSonaLightBase):
    """inSona双模式灯（支持色温和RGB）。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict):
        """初始化inSona双模式灯。"""
        super().__init__(gateway, device)
        # 支持两种颜色模式
        self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
        self._attr_supported_features = LightEntityFeature.TRANSITION
        self._attr_min_color_temp_kelvin = 2700  # 最低色温 2700K
        self._attr_max_color_temp_kelvin = 6500  # 最高色温 6500K
        
        # 根据当前func决定当前颜色模式
        self._update_color_mode_from_func()
    
    def _update_color_mode_from_func(self):
        """根据当前func更新颜色模式。"""
        if self.device.get("func") == FUNC_CTL:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif self.device.get("func") == FUNC_HSL:
            self._attr_color_mode = ColorMode.HS
        else:
            # 默认为色温模式
            self._attr_color_mode = ColorMode.COLOR_TEMP
    
    @callback
    def _handle_status_update(self) -> None:
        """处理设备状态更新。"""
        # 当设备状态更新时，根据func更新颜色模式
        self._update_color_mode_from_func()
        self.async_write_ha_state()
    
    @property
    def brightness(self) -> Optional[int]:
        """获取灯的亮度。"""
        if len(self.device["value"]) > 1:
            return int(self.device["value"][1] * 255 / 100)
        return None
    
    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """获取灯的色温（开尔文温度）。"""
        if self.color_mode == ColorMode.COLOR_TEMP and len(self.device["value"]) > 2:
            # 将设备的色温值(0-100)转换为开尔文温度(2700K-6500K)
            ct_device_value = self.device["value"][2]
            # 正确映射: 0 -> 2700K, 100 -> 6500K
            kelvin = self.min_color_temp_kelvin + (ct_device_value / 100) * (self.max_color_temp_kelvin - self.min_color_temp_kelvin)
            return int(kelvin)
        return None
    
    @property
    def hs_color(self) -> Optional[Tuple[float, float]]:
        """获取灯的HSL颜色。"""
        if self.color_mode == ColorMode.HS and len(self.device["value"]) > 3:
            hue = self.device["value"][2]  # hue值(0-360)
            saturation = self.device["value"][3]  # 饱和度(0-100)
            return (hue, saturation)
        return None
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """打开灯，设置亮度和颜色。"""
        # 处理色温模式
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            brightness = kwargs.get(
                ATTR_BRIGHTNESS, 
                int(self.device["value"][1] * 255 / 100) if len(self.device["value"]) > 1 else 255
            )
            brightness = int(brightness * 100 / 255)
            
            # 将开尔文色温转换为设备值(0-100)
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            # 确保在允许范围内
            kelvin = max(self.min_color_temp_kelvin, min(self.max_color_temp_kelvin, kelvin))
            # 正确映射: 2700K -> 0, 6500K -> 100
            ct_device_value = int((kelvin - self.min_color_temp_kelvin) / (self.max_color_temp_kelvin - self.min_color_temp_kelvin) * 100)
            
            transition = kwargs.get(ATTR_TRANSITION, 0)
            # 仅发送亮度和色温值
            await self.gateway.control_device(self.did, ACTION_CTL, [brightness, ct_device_value], transition)
            # 更新当前模式
            self.device["func"] = FUNC_CTL
            self._attr_color_mode = ColorMode.COLOR_TEMP
            return
            
        # 处理RGB模式
        elif ATTR_HS_COLOR in kwargs:
            brightness = kwargs.get(
                ATTR_BRIGHTNESS, 
                int(self.device["value"][1] * 255 / 100) if len(self.device["value"]) > 1 else 255
            )
            brightness = int(brightness * 100 / 255)
            
            hue, saturation = kwargs[ATTR_HS_COLOR]
            hue = int(hue)  # hue值(0-360)
            saturation = int(saturation)  # 饱和度(0-100)
            
            transition = kwargs.get(ATTR_TRANSITION, 0)
            # 仅发送亮度和HSL值
            await self.gateway.control_device(self.did, ACTION_HSL, [brightness, hue, saturation], transition)
            # 更新当前模式
            self.device["func"] = FUNC_HSL
            self._attr_color_mode = ColorMode.HS
            return
            
        # 只调节亮度
        elif ATTR_BRIGHTNESS in kwargs:
            brightness = int(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            transition = kwargs.get(ATTR_TRANSITION, 0)
            
            # 根据当前模式选择控制方法
            if self.color_mode == ColorMode.COLOR_TEMP:
                ct_value = self.device["value"][2] if len(self.device["value"]) > 2 else 50
                await self.gateway.control_device(self.did, ACTION_CTL, [brightness, ct_value], transition)
            elif self.color_mode == ColorMode.HS:
                hue = self.device["value"][2] if len(self.device["value"]) > 2 else 0
                saturation = self.device["value"][3] if len(self.device["value"]) > 3 else 100
                await self.gateway.control_device(self.did, ACTION_HSL, [brightness, hue, saturation], transition)
            return
            
        # 如果没有颜色或亮度参数，仅打开灯
        await super().async_turn_on(**kwargs) 