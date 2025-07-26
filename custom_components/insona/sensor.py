"""inSona网关传感器平台。"""
import logging
from typing import Any, Optional

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_SENSOR
from .gateway import InSonaGateway

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES = {
    1: {  # 温度传感器
        "device_class": SensorDeviceClass.TEMPERATURE,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
        "name": "Temperature",
    },
    2: {  # 湿度传感器
        "device_class": SensorDeviceClass.HUMIDITY,
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "name": "Humidity",
    },
    3: {  # PM2.5传感器
        "device_class": SensorDeviceClass.PM25,
        "native_unit_of_measurement": CONCENTRATION_PARTS_PER_MILLION,
        "state_class": SensorStateClass.MEASUREMENT,
        "name": "PM2.5",
    },
    4: {  # 光照度传感器
        "device_class": SensorDeviceClass.ILLUMINANCE,
        "native_unit_of_measurement": LIGHT_LUX,
        "state_class": SensorStateClass.MEASUREMENT,
        "name": "Illuminance",
    },
}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: dict,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置inSona网关传感器平台。"""
    gateway: InSonaGateway = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    
    # 为每个传感器设备创建实体
    for device in gateway.devices.values():
        if device["type"] == DEVICE_TYPE_SENSOR:
            sensor_type = device.get("sensorType", 0)
            if sensor_type in SENSOR_TYPES:
                entities.append(InSonaSensor(gateway, device, sensor_type))
    
    async_add_entities(entities)


class InSonaSensor(SensorEntity):
    """inSona传感器实体。"""
    
    def __init__(self, gateway: InSonaGateway, device: dict, sensor_type: int):
        """初始化传感器实体。"""
        self.gateway = gateway
        self.device = device
        self.sensor_type = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{device['did']}"
        self._attr_name = f"{device['name']} {SENSOR_TYPES[sensor_type]['name']}"
        self._attr_device_class = SENSOR_TYPES[sensor_type]["device_class"]
        self._attr_native_unit_of_measurement = SENSOR_TYPES[sensor_type]["native_unit_of_measurement"]
        self._attr_state_class = SENSOR_TYPES[sensor_type]["state_class"]
        
        # 注册状态更新回调
        self._remove_listener = self.gateway.register_status_listener(
            self.device["did"], self._handle_status_update
        )
    
    @property
    def native_value(self) -> Optional[Any]:
        """获取传感器的值。"""
        # 传感器值通常存储在value数组的第一个元素
        if self.device["value"] and len(self.device["value"]) > 0:
            return self.device["value"][0]
        return None
    
    @property
    def available(self) -> bool:
        """传感器是否可用。"""
        return self.gateway.connected
    
    def _handle_status_update(self) -> None:
        """处理状态更新。"""
        self.async_write_ha_state()
    
    async def async_will_remove_from_hass(self) -> None:
        """从HA中移除时的清理工作。"""
        if self._remove_listener:
            self._remove_listener()