namespace DataNexus.Server.Configs
{
    // 前端 MSAL 配置（由 ConfigController 下发给 SPA；对应 appsettings 的 "MSAL" 段）。
    public class MSALConfig
    {
        public AuthConfig Auth { get; set; } = new();
        public CacheConfig Cache { get; set; } = new();
    }

    public class AuthConfig
    {
        public string ClientId { get; set; } = "";
        public string Authority { get; set; } = "";
        public string Scope { get; set; } = "";
    }

    public class CacheConfig
    {
        public string CacheLocation { get; set; } = "";
        public bool StoreAuthStateInCookie { get; set; }
    }
}
