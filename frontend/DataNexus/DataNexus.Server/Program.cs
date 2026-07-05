using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Data.SqlClient;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Identity.Web;
using System.Security.Claims;
using DataNexus.Server.Configs;
using DataNexus.Server.Services;

namespace DataNexus.Server
{
    public class Program
    {
        public static void Main(string[] args)
        {
            var builder = WebApplication.CreateBuilder(args);

            builder.Services.AddMemoryCache();
            builder.Services.AddHttpContextAccessor();

            // AAD JWT 认证：验证 Bearer 令牌，并校验用户是否在 nexus.app_user 白名单里（缓存 10 分钟）
            builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
                .AddMicrosoftIdentityWebApi(options =>
                {
                    options.Events = new JwtBearerEvents
                    {
                        OnTokenValidated = async context =>
                        {
                            var identity = context.Principal?.Identity as ClaimsIdentity;
                            if (identity == null) return;

                            // 取用户名：preferred_username；应用令牌则用 appid
                            var usernameClaim = identity.FindFirst(ClaimConstants.PreferredUserName)
                                ?? (identity.FindFirst("idtyp")?.Value == "app" ? identity.FindFirst("appid") : null);
                            if (usernameClaim == null)
                            {
                                context.Fail("This client is not authorized");
                                return;
                            }

                            var cache = context.HttpContext.RequestServices.GetRequiredService<IMemoryCache>();
                            var cacheKey = $"AuthUser:{usernameClaim.Value}";
                            if (!cache.TryGetValue(cacheKey, out bool isAuthorized))
                            {
                                var sql = context.HttpContext.RequestServices.GetRequiredService<SqlService>();
                                var countObj = await sql.ExecuteScalarAsync(
                                    "SELECT COUNT(*) FROM nexus.app_user WHERE user_name = @userName",
                                    new[] { new SqlParameter("@userName", usernameClaim.Value) });
                                isAuthorized = Convert.ToInt32(countObj) > 0;
                                cache.Set(cacheKey, isAuthorized, TimeSpan.FromMinutes(10));
                            }
                            if (!isAuthorized)
                            {
                                context.Fail("This client is not authorized");
                                return;
                            }

                            // 归一化 Name 声明为 user_name（供 User.Identity.Name 使用）
                            foreach (var c in identity.FindAll(ClaimTypes.Name).ToArray())
                                identity.RemoveClaim(c);
                            identity.AddClaim(new Claim(ClaimTypes.Name, usernameClaim.Value));
                        }
                    };
                }, options => builder.Configuration.Bind("AzureAdLogin", options));

            builder.Services.AddControllers();
            builder.Services.AddScoped<SqlService>();

            // 配置段（供 ConfigController 下发给前端）
            builder.Services.Configure<MSALConfig>(builder.Configuration.GetSection("MSAL"));
            builder.Services.Configure<BackendAPIConfig>(builder.Configuration.GetSection("BackendAPI"));

            var app = builder.Build();

            app.UseDefaultFiles();
            app.MapStaticAssets();

            // Configure the HTTP request pipeline.

            app.UseHttpsRedirection();

            app.UseAuthentication();
            app.UseAuthorization();

            app.MapControllers();

            app.MapFallbackToFile("/index.html");

            app.Run();
        }
    }
}
