using System.Text.Json;
using static ExecutionFiles;

static class ExecutionServiceChecks
{
    public static async Task Run()
    {
        var directory = Path.Combine(Path.GetTempPath(), "aurum-service-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        using var shutdown = new CancellationTokenSource();
        Task? service = null;
        void Check(bool value, string message) { if (!value) throw new Exception(message); }
        try
        {
            Save(Path.Combine(directory, "app.json"), new AppCredentials("test", "test"));
            Save(Path.Combine(directory, "tokens.json"), new TokenSet("test", "test", DateTimeOffset.UtcNow.AddHours(1)));
            var wire = new ExecutionChecks.FakeConnection();
            service = ExecutionService.Run(directory, shutdown.Token, () => wire);
            var firstDashboard = new ExecutionClient(directory);
            Check(!(await firstDashboard.Snapshot()).Active, "Service launch must not enable trading.");
            var report = JsonSerializer.SerializeToElement(new { config = new ResearchConfig(), results = new[] { new { name = "test", rr = 2 } } });
            await firstDashboard.Apply("custom-test", report, "test", 123);
            var applied = (await firstDashboard.Snapshot()).Config!;
            await firstDashboard.Start(applied.Revision, applied.Account.Login);
            for (int i = 0; i < 100 && (await firstDashboard.Snapshot()).Status.State != "running"; i++) await Task.Delay(20);
            Check((await firstDashboard.Snapshot()).Active, "Fake bot should remain active after request socket closes.");
            // Each request closes its socket; replacing the dashboard client must not own the bot task.
            var reopenedDashboard = new ExecutionClient(directory);
            await Task.Delay(700);
            var state = await reopenedDashboard.Snapshot();
            Check(state.Active && state.Status.State == "running" && state.Config?.Revision == applied.Revision, "Dashboard reconnect must retain the same active worker/config.");
            Check(wire.Orders == 0, "Client reconnection cannot submit orders.");
            await reopenedDashboard.Stop();
            for (int i = 0; i < 100 && (await reopenedDashboard.Snapshot()).Active; i++) await Task.Delay(20);
            Check(!(await reopenedDashboard.Snapshot()).Active, "Explicit Stop must still reach the worker.");
            // An old account response must never satisfy a request for another account.
            var fields=System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic;
            string[] names={"PrivateDirectory","Bot","AccountSnapshot","SnapshotAccount","AccountAt"};
            var previous=names.ToDictionary(n=>n,n=>typeof(DashboardServer).GetField(n,fields)!.GetValue(null));
            void Field(string name,object? value)=>typeof(DashboardServer).GetField(name,fields)!.SetValue(null,value);
            var appPath=Path.Combine(directory,"app.json");
            File.Move(appPath,appPath+".test");
            try
            {
                Field("PrivateDirectory",directory);Field("Bot",reopenedDashboard);
                var cached=new {login="old-account"};Field("AccountSnapshot",cached);
                Field("SnapshotAccount",applied.Account with {Id=999});Field("AccountAt",DateTime.UtcNow);
                Task<object> ReadAccount()=>(Task<object>)typeof(DashboardServer).GetMethod("Account",fields)!.Invoke(null,null)!;
                bool invalidated=false;
                try {await ReadAccount();} catch(FileNotFoundException){invalidated=true;}
                Check(invalidated,"Another account's cache must be discarded before credentials/broker access");
                Field("SnapshotAccount",applied.Account);
                Check(ReferenceEquals(await ReadAccount(),cached),"Same-account fresh cache should still work without broker requests");
            }
            finally
            {
                File.Move(appPath+".test",appPath);
                foreach(var item in previous)Field(item.Key,item.Value);
            }
            shutdown.Cancel(); await service;
            Check((await reopenedDashboard.Snapshot()).Status.State == "offline", "Unavailable worker must not report LIVE.");
            Console.WriteLine("Execution service checks PASS: no autostart, active fake bot survives dashboard reconnect, same config, explicit stop, account cache isolation, offline detection. No broker orders.");
        }
        finally
        {
            shutdown.Cancel();
            if (service is not null) await service;
            Directory.Delete(directory, true);
        }
    }
}
