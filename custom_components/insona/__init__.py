"""inSona网关集成组件"""
import asyncio
import logging
import json
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    Platform,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, DEFAULT_PORT
from .gateway import InSonaGateway
from .scene import InSonaScene

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.LIGHT,
    Platform.COVER,
    Platform.SENSOR,
    Platform.SCENE,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置来自配置流的inSona网关条目。"""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    
    gateway = InSonaGateway(hass, host, port)
    gateway_id = f"{host}:{port}"
    
    try:
        # 注册网关设备
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, gateway_id)},
            manufacturer="inSona",
            name=f"inSona 网关 ({host})",
            model="inSona Gateway",
        )
        
        await gateway.connect()
        await gateway.query_devices()
        _LOGGER.info("开始查询场景列表")
        await gateway.query_scenes()
        _LOGGER.info("场景列表查询完成")
    except (asyncio.TimeoutError, ConnectionRefusedError) as err:
        await gateway.disconnect()
        raise ConfigEntryNotReady(f"无法连接到inSona网关: {err}") from err
    except Exception as err:
        await gateway.disconnect()
        _LOGGER.exception("设置inSona网关时出错，特别是在查询场景时: %s", err)
        raise ConfigEntryNotReady(f"初始化inSona网关失败，特别是在查询场景时: {err}") from err
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = gateway
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # 注册关闭回调
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """处理配置项更新。"""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载一个配置项。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        gateway = hass.data[DOMAIN].pop(entry.entry_id)
        await gateway.disconnect()
    
    return unload_ok