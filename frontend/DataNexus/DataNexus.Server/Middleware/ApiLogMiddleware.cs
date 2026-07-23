using DataNexus.Server.Services;
using Microsoft.AspNetCore.Mvc.Controllers;
using Microsoft.Data.SqlClient;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace DataNexus.Server.Middleware
{
    /// <summary>
    /// 记录所有经过 BFF 的 HTTP 请求到 nexus.api_log。
    /// 请求/响应正文仅记录 JSON 或文本，最多 64 KiB；敏感字段递归脱敏。
    /// 日志写入失败不会改变原请求结果。
    /// </summary>
    public sealed class ApiLogMiddleware
    {
        private const int MaxBodyBytes = 64 * 1024;
        private const string TruncatedMarker = "\n…[truncated]";
        private readonly RequestDelegate _next;
        private readonly ILogger<ApiLogMiddleware> _logger;

        public ApiLogMiddleware(RequestDelegate next, ILogger<ApiLogMiddleware> logger)
        {
            _next = next;
            _logger = logger;
        }

        public async Task InvokeAsync(HttpContext context, SqlService sql)
        {
            var startedAt = DateTime.UtcNow;
            var stopwatch = Stopwatch.StartNew();
            var originalPath = context.Request.Path.Value ?? "/";
            var requestPayload = await ReadRequestBodyAsync(context.Request);
            var captureResponse = context.Request.Path.StartsWithSegments("/api");
            var originalResponseBody = context.Response.Body;
            LimitedCaptureStream? responseCapture = null;
            Exception? exception = null;

            if (captureResponse)
            {
                responseCapture = new LimitedCaptureStream(originalResponseBody, MaxBodyBytes);
                context.Response.Body = responseCapture;
            }

            try
            {
                await _next(context);
            }
            catch (Exception ex)
            {
                exception = ex;
                if (!context.Response.HasStarted)
                    context.Response.StatusCode = StatusCodes.Status500InternalServerError;
                throw;
            }
            finally
            {
                stopwatch.Stop();
                if (responseCapture != null)
                    context.Response.Body = originalResponseBody;

                var responseText = responseCapture == null
                    ? null
                    : SanitizeBody(
                        responseCapture.GetCapturedText(),
                        context.Response.ContentType,
                        responseCapture.WasTruncated);
                var responseError = ExtractResponseError(responseText);
                var state = DeriveState(context.Response.StatusCode, exception, responseError?.State);
                var message = exception?.ToString() ?? responseError?.Message;
                var userName = context.User.Identity?.Name;
                var functionName = ResolveFunctionName(context);

                try
                {
                    await sql.ExecuteNonQueryAsync(
                        @"INSERT INTO nexus.api_log
                              (function_name, [method], [path], user_name, payload, response,
                               [state], cost_ms, [message], [source], request_time, response_time)
                          VALUES
                              (@function, @method, @path, @user, @payload, @response,
                               @state, @cost, @message, 'bff', @requestTime, @responseTime)",
                        new[]
                        {
                            Parameter("@function", Limit(functionName, 200)),
                            Parameter("@method", Limit(context.Request.Method, 16)),
                            Parameter("@path", Limit(originalPath + context.Request.QueryString, 400)),
                            Parameter("@user", Limit(userName, 200)),
                            Parameter("@payload", requestPayload),
                            Parameter("@response", responseText),
                            Parameter("@state", state),
                            new SqlParameter("@cost", Math.Min(stopwatch.ElapsedMilliseconds, int.MaxValue)),
                            Parameter("@message", RedactPlainText(message)),
                            new SqlParameter("@requestTime", startedAt),
                            new SqlParameter("@responseTime", DateTime.UtcNow),
                        },
                        CancellationToken.None);
                }
                catch (Exception logError)
                {
                    _logger.LogError(logError,
                        "Failed to persist BFF API log for {Method} {Path}",
                        context.Request.Method,
                        originalPath);
                }
            }
        }

        private static async Task<string?> ReadRequestBodyAsync(HttpRequest request)
        {
            if (request.ContentLength == 0 || !IsTextContent(request.ContentType))
                return null;

            request.EnableBuffering();
            request.Body.Position = 0;
            var buffer = new char[MaxBodyBytes + 1];
            int count;
            using (var reader = new StreamReader(
                request.Body,
                request.ContentType?.Contains("charset=utf-16", StringComparison.OrdinalIgnoreCase) == true
                    ? Encoding.Unicode
                    : Encoding.UTF8,
                detectEncodingFromByteOrderMarks: true,
                bufferSize: 4096,
                leaveOpen: true))
            {
                count = await reader.ReadBlockAsync(buffer.AsMemory(0, buffer.Length));
            }
            request.Body.Position = 0;
            var truncated = count > MaxBodyBytes;
            var text = new string(buffer, 0, Math.Min(count, MaxBodyBytes));
            return SanitizeBody(text, request.ContentType, truncated);
        }

        private static string? SanitizeBody(string? value, string? contentType, bool truncated)
        {
            if (string.IsNullOrEmpty(value)) return value;
            string result;
            if (IsJsonContent(contentType))
            {
                try
                {
                    var node = JsonNode.Parse(value);
                    RedactNode(node);
                    result = node?.ToJsonString() ?? value;
                }
                catch (JsonException)
                {
                    result = RedactPlainText(value) ?? value;
                }
            }
            else if (contentType?.StartsWith("application/x-www-form-urlencoded", StringComparison.OrdinalIgnoreCase) == true
                     || contentType?.StartsWith("multipart/", StringComparison.OrdinalIgnoreCase) == true)
            {
                result = "[form body omitted]";
            }
            else
            {
                result = RedactPlainText(value) ?? value;
            }
            return truncated ? result + TruncatedMarker : result;
        }

        private static bool IsTextContent(string? contentType)
        {
            if (string.IsNullOrWhiteSpace(contentType)) return false;
            return IsJsonContent(contentType)
                || contentType.StartsWith("text/", StringComparison.OrdinalIgnoreCase)
                || contentType.StartsWith("application/xml", StringComparison.OrdinalIgnoreCase)
                || contentType.StartsWith("application/x-www-form-urlencoded", StringComparison.OrdinalIgnoreCase)
                || contentType.StartsWith("multipart/", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsJsonContent(string? contentType)
        {
            return !string.IsNullOrWhiteSpace(contentType)
                && (contentType.Contains("application/json", StringComparison.OrdinalIgnoreCase)
                    || contentType.Contains("+json", StringComparison.OrdinalIgnoreCase));
        }

        private static readonly HashSet<string> SensitiveKeys = new(
            new[]
            {
                "password", "pwd", "key", "api_key", "apikey", "client_secret",
                "secret", "token", "access_token", "refresh_token", "authorization",
            },
            StringComparer.OrdinalIgnoreCase);

        private static readonly Regex SensitiveText = new(
            "(?ix)\\b(password|pwd|client_secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)\\s*[=:]\\s*([^;,\\s\\\"'}]+)",
            RegexOptions.Compiled,
            TimeSpan.FromMilliseconds(100));

        private static void RedactNode(JsonNode? node)
        {
            if (node is JsonObject obj)
            {
                foreach (var key in obj.Select(item => item.Key).ToList())
                {
                    if (SensitiveKeys.Contains(key)) obj[key] = "***";
                    else RedactNode(obj[key]);
                }
            }
            else if (node is JsonArray array)
            {
                foreach (var item in array) RedactNode(item);
            }
        }

        private static string? RedactPlainText(string? value)
        {
            if (string.IsNullOrEmpty(value)) return value;
            try
            {
                return SensitiveText.Replace(value, "$1=***");
            }
            catch (RegexMatchTimeoutException)
            {
                return "[message redaction timed out]";
            }
        }

        private static (string? State, string? Message)? ExtractResponseError(string? response)
        {
            if (string.IsNullOrWhiteSpace(response)) return null;
            try
            {
                var obj = JsonNode.Parse(response) as JsonObject;
                if (obj == null) return null;
                var state = obj["state"]?.ToString();
                var message = obj["message"]?.ToString() ?? obj["detail"]?.ToString();
                return (state, message);
            }
            catch (Exception) when (response.EndsWith(TruncatedMarker, StringComparison.Ordinal))
            {
                return null;
            }
            catch (JsonException)
            {
                return null;
            }
        }

        private static string DeriveState(int statusCode, Exception? exception, string? payloadState)
        {
            if (exception != null || statusCode >= 500
                || string.Equals(payloadState, "failed", StringComparison.OrdinalIgnoreCase))
                return "failed";
            if (statusCode == StatusCodes.Status401Unauthorized) return "unauthorized";
            if (statusCode == StatusCodes.Status403Forbidden) return "denied";
            if (statusCode >= 400
                || string.Equals(payloadState, "error", StringComparison.OrdinalIgnoreCase))
                return "error";
            return "success";
        }

        private static string ResolveFunctionName(HttpContext context)
        {
            var action = context.GetEndpoint()?.Metadata.GetMetadata<ControllerActionDescriptor>();
            if (action != null) return $"{action.ControllerName}.{action.ActionName}";
            return context.GetEndpoint()?.DisplayName ?? "http";
        }

        private static SqlParameter Parameter(string name, string? value)
        {
            return new SqlParameter(name, (object?)value ?? DBNull.Value);
        }

        private static string? Limit(string? value, int maxLength)
        {
            if (string.IsNullOrEmpty(value) || value.Length <= maxLength) return value;
            return value[..maxLength];
        }

        private sealed class LimitedCaptureStream : Stream
        {
            private readonly Stream _inner;
            private readonly MemoryStream _capture;
            private readonly int _limit;

            public LimitedCaptureStream(Stream inner, int limit)
            {
                _inner = inner;
                _limit = limit;
                _capture = new MemoryStream(limit);
            }

            public bool WasTruncated { get; private set; }
            public override bool CanRead => false;
            public override bool CanSeek => false;
            public override bool CanWrite => _inner.CanWrite;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }

            public string GetCapturedText() => Encoding.UTF8.GetString(_capture.ToArray());
            public override void Flush() => _inner.Flush();
            public override Task FlushAsync(CancellationToken cancellationToken) => _inner.FlushAsync(cancellationToken);

            public override void Write(byte[] buffer, int offset, int count)
            {
                Capture(buffer.AsSpan(offset, count));
                _inner.Write(buffer, offset, count);
            }

            public override async Task WriteAsync(
                byte[] buffer,
                int offset,
                int count,
                CancellationToken cancellationToken)
            {
                Capture(buffer.AsSpan(offset, count));
                await _inner.WriteAsync(buffer.AsMemory(offset, count), cancellationToken);
            }

            public override async ValueTask WriteAsync(
                ReadOnlyMemory<byte> buffer,
                CancellationToken cancellationToken = default)
            {
                Capture(buffer.Span);
                await _inner.WriteAsync(buffer, cancellationToken);
            }

            private void Capture(ReadOnlySpan<byte> buffer)
            {
                var remaining = _limit - (int)_capture.Length;
                if (remaining > 0)
                {
                    var take = Math.Min(remaining, buffer.Length);
                    _capture.Write(buffer[..take]);
                }
                if (buffer.Length > remaining) WasTruncated = true;
            }

            public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
        }
    }
}
