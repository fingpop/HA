"""inSona网关场景支持。"""
import logging
from typing import List, Dict, Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置inSona场景平台。"""
    gateway = hass.data[DOMAIN][config_entry.entry_id]
    
    # 创建场景实体
    entities = []
    for scene_id, scene_name in gateway.scenes.items():
        entities.append(InSonaScene(gateway, scene_id, scene_name))
    
    async_add_entities(entities)
    _LOGGER.info("已添加 %d 个inSona场景", len(entities))


class InSonaScene(Scene):
    """inSona场景实体。"""

    def __init__(self, gateway, scene_id: int, name: str):
        """初始化场景实体。"""
        self._gateway = gateway
        self._scene_id = scene_id
        self._attr_name = name
        self._attr_unique_id = f"{gateway.host}_{scene_id}"
        
    @property
    def device_info(self) -> DeviceInfo:
        """返回设备信息。"""
        return DeviceInfo(
            identifiers={(DOMAIN, self._gateway.host)},
            manufacturer="inSona",
            name=f"inSona 网关 ({self._gateway.host})",
            model="inSona Gateway",
        )

    async def async_activate(self, **kwargs: Any) -> None:
        """激活场景。"""
        _LOGGER.debug("激活场景: %s (ID: %s)", self._attr_name, self._scene_id)
        await self._gateway.activate_scene(self._scene_id)