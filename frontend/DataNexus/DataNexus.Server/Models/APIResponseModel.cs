namespace DataNexus.Server.Models
{
    // 统一响应信封：{ state, message, data }（前端 common/API.ts 据此解包）。
    public class APIResponseModel
    {
        public string State { get; set; } = "success";
        public string? Message { get; set; }
        public object? Data { get; set; }
    }
}
