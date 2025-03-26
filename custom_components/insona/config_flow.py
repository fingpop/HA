"""inSona网关集成的配置流程。"""
import asyncio
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_PORT
from .gateway import InSonaGateway

_LOGGER = logging.getLogger(__name__)

class InSonaFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """处理inSona网关配置流程。"""
    
    VERSION = 1
    
    async def async_step_user(self, user_input=None) -> FlowResult:
        """处理用户输入配置。"""
        errors = {}
        
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            
            # 检查是否已经配置过此网关
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            
            # 测试连接
            gateway = InSonaGateway(self.hass, host, port)
            try:
                await gateway.connect()
                await gateway.query_devices()
                await gateway.disconnect()
                
                return self.async_create_entry(
                    title=f"inSona 网关 ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                    },
                )
            except asyncio.TimeoutError:
                errors["base"] = "timeout"
            except ConnectionRefusedError:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("连接测试失败: %s", err)
                errors["base"] = "unknown"
                
            await gateway.disconnect()
        
        # 显示配置表单
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        ) 