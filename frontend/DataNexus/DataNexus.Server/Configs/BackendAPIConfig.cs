namespace DataNexus.Server.Configs
{
    // 后端（Python 引擎）地址，前端据此拼完整 URL 直连后端（对应 appsettings 的 "BackendAPI" 段）。
    public class BackendAPIConfig
    {
        public string BaseUrl { get; set; } = "";
        public string Version { get; set; } = "";
    }
}
