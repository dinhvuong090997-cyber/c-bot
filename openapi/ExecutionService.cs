using System.Buffers.Binary;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text.Json;
using static ExecutionFiles;

sealed record ExecutionSnapshot(ExecutionConfig? Config, ExecutionView Status, bool Active);

// Private Unix socket: only the workspace owner can reach the execution controls.
static class ExecutionService
{
    const int MaxMessage = 8 * 1024 * 1024;
    internal static async Task<JsonElement> Read(Stream stream, CancellationToken cancellation)
    {
        var header = new byte[4];
        await stream.ReadExactlyAsync(header, cancellation);
        var length = BinaryPrimitives.ReadInt32LittleEndian(header);
        if (length is <= 0 or > MaxMessage) throw new IOException("Invalid execution message size.");
        var bytes = new byte[length];
        await stream.ReadExactlyAsync(bytes, cancellation);
        using var doc = JsonDocument.Parse(bytes);
        return doc.RootElement.Clone();
    }
    internal static async Task Write(Stream stream, object message, CancellationToken cancellation)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(message, Json);
        if (bytes.Length > MaxMessage) throw new IOException("Execution message too large.");
        var header = new byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(header, bytes.Length);
        await stream.WriteAsync(header, cancellation);
        await stream.WriteAsync(bytes, cancellation);
    }
    static async Task Handle(Socket socket, ExecutionBot bot)
    {
        using (socket)
        using (var stream = new NetworkStream(socket, ownsSocket: false))
        using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90)))
        {
            try
            {
                var request = await Read(stream, timeout.Token);
                var body = request.GetProperty("body");
                object result = request.GetProperty("action").GetString() switch
                {
                    "snapshot" => bot.Snapshot(),
                    "accounts" => await bot.Accounts(),
                    "apply" => await bot.Apply(body.GetProperty("reportId").GetString()!, body.GetProperty("report"), body.GetProperty("run").GetString()!, Integer(body, "accountId")),
                    "start" => await bot.Start(body.GetProperty("revision").GetString()!, body.GetProperty("accountLogin").GetString()!),
                    "stop" => await bot.Stop(),
                    _ => throw new ArgumentException("Unknown execution command.")
                };
                await Write(stream, new { ok = true, result }, timeout.Token);
            }
            catch (Exception ex)
            {
                try { await Write(stream, new { ok = false, error = ex is ArgumentException ? ex.Message : "Execution service request failed." }, timeout.Token); }
                catch (Exception sendError) when (sendError is IOException or SocketException or OperationCanceledException) { }
            }
        }
    }
    public static async Task Run(string directory, CancellationToken cancellation = default, Func<IExecutionConnection>? factory = null)
    {
        using var lease = new FileStream(Path.Combine(directory, "execution-service.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        var path = Path.Combine(directory, "execution.sock");
        File.Delete(path);
        using var listener = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
        listener.Bind(new UnixDomainSocketEndPoint(path));
        File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        listener.Listen(16);
        var bot = new ExecutionBot(directory, factory);
        using var shutdown = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        using var term = PosixSignalRegistration.Create(PosixSignal.SIGTERM, context => { context.Cancel = true; shutdown.Cancel(); });
        Console.WriteLine("Execution service ready; dashboard connections do not control its lifetime.");
        try
        {
            while (true) _ = Handle(await listener.AcceptAsync(shutdown.Token), bot);
        }
        catch (OperationCanceledException) when (shutdown.IsCancellationRequested) { }
        finally
        {
            await bot.Stop();
            var deadline = DateTime.UtcNow.AddSeconds(35);
            while (bot.IsRunning && DateTime.UtcNow < deadline) await Task.Delay(100);
            File.Delete(path);
        }
    }
}

sealed class ExecutionClient(string directory)
{
    async Task<JsonElement> Call(string action, object? body = null)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        using var socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
        await socket.ConnectAsync(new UnixDomainSocketEndPoint(Path.Combine(directory, "execution.sock")), timeout.Token);
        using var stream = new NetworkStream(socket, ownsSocket: false);
        await ExecutionService.Write(stream, new { action, body = body ?? new { } }, timeout.Token);
        var reply = await ExecutionService.Read(stream, timeout.Token);
        if (!reply.GetProperty("ok").GetBoolean()) throw new ArgumentException(reply.GetProperty("error").GetString());
        return reply.GetProperty("result").Clone();
    }
    public async Task<ExecutionSnapshot> Snapshot()
    {
        try { return (await Call("snapshot")).Deserialize<ExecutionSnapshot>(Json)!; }
        catch (Exception ex) when (ex is IOException or SocketException or OperationCanceledException or JsonException)
        {
            var path = Path.Combine(directory, "execution-config.json");
            var config = File.Exists(path) ? JsonSerializer.Deserialize<ExecutionConfig>(File.ReadAllText(path), Json) : null;
            return new(config, new("offline", "Cannot reach the execution service. Dashboard reconnection does not start or stop the bot."), false);
        }
    }
    public Task<JsonElement> Accounts() => Call("accounts");
    public Task<JsonElement> Apply(string reportId, JsonElement report, string run, long accountId) => Call("apply", new { reportId, report, run, accountId });
    public Task<JsonElement> Start(string revision, string accountLogin) => Call("start", new { revision, accountLogin });
    public Task<JsonElement> Stop() => Call("stop");
}
