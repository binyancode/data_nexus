using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using DataNexus.Server.Configs;
using DataNexus.Server.Models;

namespace DataNexus.Server.Controllers
{
    // 下发前端所需配置：config/MSAL（登录）、config/BackendAPI（后端地址）。
    [ApiController]
    [Route("api/[controller]")]
    public class ConfigController : ControllerBase
    {
        private readonly MSALConfig _msalConfig;
        private readonly BackendAPIConfig _backendApiConfig;

        public ConfigController(IOptions<MSALConfig> msalConfig, IOptions<BackendAPIConfig> backendApiConfig)
        {
            _msalConfig = msalConfig.Value;
            _backendApiConfig = backendApiConfig.Value;
        }

        [HttpGet("MSAL")]
        public APIResponseModel MSAL() => new() { Data = _msalConfig };

        [HttpGet("BackendAPI")]
        public APIResponseModel BackendAPI() => new() { Data = _backendApiConfig };
    }
}
