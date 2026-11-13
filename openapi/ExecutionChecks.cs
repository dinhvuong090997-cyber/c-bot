using System.Text.Json;
using Xauusd;
using static ExecutionFiles;

static class ExecutionChecks
{
    static JsonElement E(object value) => JsonSerializer.SerializeToElement(value);
    static void Check(bool value, string message) { if (!value) throw new Exception("Execution check failed: " + message); }
    static void Reject(Action action, string message) { try { action(); } catch (ArgumentException) { return; } throw new Exception("Accepted: " + message); }
    public static async Task Run()
    {
        await HistoryChecks.Run();
        var account = new ExecutionAccount(123, "456", "FxPro", false);
        var report = E(new { config = new ResearchConfig(RR: 5, RiskPercent: 1, MaxDrawdownPercent: 20, MinimumStop: 3, NewYork: false), results = new[] { new { name = "run", rr = 5 } } });
        var config = ExecutionConfig.FromReport("custom-test", report, "run", account);
        Check(config.RR == 5 && config.RiskPercent == 1 && config.MinimumStop == 3 && !config.NewYork && config.Account.Id == 123, "exact config mapping");
        Reject(() => ExecutionConfig.FromReport("x", report, "missing", account), "unknown run");
        Reject(() => (config with { RR = double.NaN }).Validate(), "NaN");
        Reject(() => (config with { Asia = false, NewYork = false }).Validate(), "no sessions");
        var symbol = E(new { digits = 2, minVolume = 100, maxVolume = 1000000, stepVolume = 100 });
        var order = ExecutionOrder.Size(config, 50000, 3000, 3.001, symbol)!;
        Check(order.Volume == 1600 && order.RelativeStopLoss == 301000 && order.RelativeTakeProfit == 1505000, "units, notional cap, rounded protection");
        Check(ExecutionOrder.Size(config, 1000, 3000, 3, symbol) is null, "never round above min volume/risk cap");
        var payload = E(ExecutionBot.OrderPayload(config, 41, order, false, "test"));
        Check(payload.GetProperty("tradeSide").GetInt32() == 2 && payload.GetProperty("relativeStopLoss").GetInt64() == 301000 && !payload.TryGetProperty("stopLoss", out _), "relative server protection on market order");
        var risk = new ExecutionRisk();risk.Update(50000, 5);risk.Update(52000, 5);
        Check(risk.Update(49399, 5) && risk.Update(55000, 5), "drawdown halt survives balance recovery");
        var signal = new ExecutionSignal(config);
        DateTime day = new(2026, 1, 5, 0, 0, 0, DateTimeKind.Utc);
        for(int i=0;i<480;i++)signal.Observe(day.AddMinutes(i), 3000+i*.01,3000.2+i*.01);
        for(int i=0;i<31;i++)signal.Observe(day.AddHours(7).AddMinutes(59).AddSeconds(i),3005,3005.2);
        signal.Observe(day.AddHours(7).AddMinutes(59).AddSeconds(59),3005,3005.2);
        signal.Observe(day.AddHours(8),3005,3005.2);
        var next=day.AddDays(1);signal.Observe(next,3005,3005.2);
        Check(signal.Ready(next,3005,3005.2,false) is null,"one second delay");
        Check(signal.Ready(next.AddMilliseconds(500),3005,3005.2,false) is null,"not early");
        Check(signal.Ready(next.AddSeconds(1),3005,3005.2,false) is not null,"eligible entry");
        Check(signal.Ready(next.AddSeconds(2),3005,3005.2,false) is null,"one attempt per minute");
        signal.Ready(next.AddMinutes(1),3005,3005.2,false);
        Check(signal.Ready(next.AddMinutes(1).AddSeconds(7),3005,3005.2,false) is null,"stale pending entry");
        signal.Ready(next.AddMinutes(2),3005,3005.2,false);
        Check(signal.Ready(next.AddMinutes(2).AddSeconds(1),3005,3005.2,true) is null,"existing exposure/stop blocks entry");
        Check(!ExecutionBroker.Protected(E(new { stopLoss=2990 })),"missing TP");
        Check(ExecutionBroker.HasExposure(E(new { order=new[]{new { orderId=1 }} })),"pending orders block entry");
        Reject(()=>ExecutionBroker.ValidateTrader(E(new {isLimitedRisk=true})),"guaranteed stop account unsupported");
        var directory=Path.Combine(Path.GetTempPath(),"aurum-execution-check-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
        try
        {
            Save(Path.Combine(directory,"app.json"),new AppCredentials("test","test"));
            Save(Path.Combine(directory,"tokens.json"),new TokenSet("test","test",DateTimeOffset.UtcNow.AddHours(1)));
            var intentFile=Path.Combine(directory,"intent.json");
            var intent=new ExecutionRisk {Peak=50000};
            var submitWire=new FakeConnection {Journal=intentFile};
            await ExecutionBot.Submit(submitWire,config,41,order,true,intent,intentFile);
            Check(submitWire.Orders==1&&submitWire.IntentPersisted,"intent persisted before broker send");
            bool duplicateBlocked=false;
            try{await ExecutionBot.Submit(submitWire,config,41,order,true,intent,intentFile);}catch(ArgumentException){duplicateBlocked=true;}
            Check(duplicateBlocked&&submitWire.Orders==1,"unresolved order cannot be resent");
            intent.PendingOrder=null;submitWire.FailOrder=true;
            bool timeout=false;
            try{await ExecutionBot.Submit(submitWire,config,41,order,true,intent,intentFile);}catch(IOException){timeout=true;}
            Check(timeout&&submitWire.Orders==2&&JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(intentFile),Json)!.PendingOrder is not null,"ambiguous send keeps intent without retry");
            var lifecycleFile=Path.Combine(directory,"lifecycle.json");
            var lifecycleRisk=new ExecutionRisk {Peak=50000};
            var lifecycleWire=new FakeConnection {Journal=lifecycleFile,ProtectedAfterEvent=true};
            bool finished=false;
            lifecycleWire.Received=(type,p)=>{if(type==2126)finished|=ExecutionBot.IsTerminalOpeningOrder(p,lifecycleRisk.PendingOrder);};
            await ExecutionBot.Submit(lifecycleWire,config,41,order,true,lifecycleRisk,lifecycleFile);
            var clientId=lifecycleRisk.PendingOrder;
            void Event(int kind,int type=1,bool closing=false,string? id=null) => lifecycleWire.Received!(2126,E(new {ctidTraderAccountId=123,executionType=kind,order=new {orderType=type,closingOrder=closing,clientOrderId=id??clientId}}));
            Event(2); Event(11); Event(3,4,true); Event(3,id:"another-order");
            Check(!finished&&JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(lifecycleFile),Json)!.PendingOrder==clientId,"accepted/partial/protection/unrelated events cannot resolve the original order");
            Event(3);
            Check(finished&&lifecycleRisk.PendingOrder==clientId,"full fill retains intent until fresh protection reconciliation");
            var lifecycleBroker=new ExecutionBroker {Api=lifecycleWire,Account=account,Symbol=symbol,Trader=E(new {balance=5000000,moneyDigits=2})};
            await ExecutionBot.CheckProtection(lifecycleBroker,lifecycleRisk,lifecycleFile,await lifecycleBroker.Reconcile(),new());
            ExecutionBot.ConfirmPending(lifecycleRisk,lifecycleFile);
            Check(JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(lifecycleFile),Json)!.PendingOrder is null&&!lifecycleRisk.Halted&&lifecycleWire.Closes==0,"protected filled order resolves its durable journal without emergency close");
            foreach(int kind in new[]{5,6,7})Check(ExecutionBot.IsTerminalOpeningOrder(E(new {executionType=kind,order=new {orderType=1,closingOrder=false,clientOrderId=clientId}}),clientId),"cancel/expire/reject are terminal");
            var wire=new FakeConnection();var bot=new ExecutionBot(directory,()=>wire);
            await bot.Apply("custom-test",report,"run",123);
            Check(wire.Orders==0,"apply cannot trade");
            // Hold the Start critical section and reproduce its reset while Stop waits.
            var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
            var gate = (SemaphoreSlim)typeof(ExecutionBot).GetField("commands", flags)!.GetValue(bot)!;
            var stopFlag = typeof(ExecutionBot).GetField("stopRequested", flags)!;
            await gate.WaitAsync();
            var queuedStop = bot.Stop();
            stopFlag.SetValue(bot, false);
            gate.Release(); await queuedStop;
            Check((bool)stopFlag.GetValue(bot)!, "Stop must win after a concurrent Start resets the early flag");

            var restored = new ExecutionBot(directory,()=>wire);
            Check(!restored.IsRunning&&JsonSerializer.Serialize(restored.Snapshot(),Json).Contains("Saved config loaded"),"service restart restores config without autostart");
            using var applied=JsonDocument.Parse(JsonSerializer.Serialize(bot.Snapshot(),Json));
            var revision=applied.RootElement.GetProperty("config").GetProperty("revision").GetString()!;
            bool rejected=false;try{await bot.Start("stale","456");}catch(ArgumentException){rejected=true;}
            Check(rejected,"stale start review rejected");
            await bot.Start(revision,"456");
            rejected=false;try{await bot.Start(revision,"456");}catch(ArgumentException){rejected=true;}
            Check(rejected,"double start rejected");
            await bot.Stop();
            for(int i=0;i<100&&bot.IsRunning;i++)await Task.Delay(10);
            Check(!bot.IsRunning&&wire.Orders==0,"stop/no profile cannot place an order");
            wire.HoldHistory=true;
            await bot.Start(revision,"456");
            await wire.HistoryEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            await bot.Stop();wire.HistoryRelease.TrySetResult();
            for(int i=0;i<100&&bot.IsRunning;i++)await Task.Delay(10);
            Check(!bot.IsRunning&&JsonSerializer.Serialize(bot.Snapshot(),Json).Contains("Startup cancelled")&&wire.Orders==0,"Stop during historical request cancels bootstrap without orders");
            wire.HoldHistory=false;
            var riskPath=Path.Combine(directory,"execution-risk-False-123.json");
            Save(riskPath,new ExecutionRisk {Peak=50000,PendingOrder="unknown-order"});
            await bot.Start(revision,"456");for(int i=0;i<100&&bot.IsRunning;i++)await Task.Delay(10);
            Check(JsonSerializer.Serialize(bot.Snapshot(),Json).Contains("unknown outcome")&&wire.Orders==0,"uncertain order survives restart without resend");
            Save(riskPath,new ExecutionRisk {Peak=50000,Halted=true});
            await bot.Start(revision,"456");for(int i=0;i<100&&bot.IsRunning;i++)await Task.Delay(10);
            Check(JsonSerializer.Serialize(bot.Snapshot(),Json).Contains("halt needs review"),"durable halt cannot be bypassed by Start");
            Save(riskPath,new ExecutionRisk {Peak=50000});wire.ProtectedAfterEvent=true;
            await bot.Start(revision,"456");
            for(int i=0;i<300&&bot.IsRunning;i++)
            {
                var snapshot=JsonSerializer.SerializeToElement(bot.Snapshot(),Json);
                if(snapshot.GetProperty("status").GetProperty("state").GetString()=="running")break;
                await Task.Delay(10);
            }
            Check(bot.IsRunning&&wire.Closes==0&&!JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(riskPath),Json)!.Halted,"partial fill event must not halt or close a position protected in fresh reconcile");
            await bot.Stop();for(int i=0;i<100&&bot.IsRunning;i++)await Task.Delay(10);
            wire.ProtectedAfterEvent=false;
            Save(riskPath,new ExecutionRisk {Peak=50000});wire.Unprotected=true;
            await bot.Start(revision,"456");for(int i=0;i<100&&bot.IsRunning;i++)await Task.Delay(10);
            Check(wire.Closes==1&&wire.Orders==0&&JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(riskPath),Json)!.Halted,"missing protection requests close and persists halt");
        }
        finally { Directory.Delete(directory,true); }
        Console.WriteLine("Execution checks PASS: mapping, sizing, protection, delayed signal, exposure, durable halt, apply/start/stop and no duplicate/uncertain resubmission. No broker orders sent.");
    }
    internal sealed class FakeConnection : IExecutionConnection
    {
        public Action<int,JsonElement>? Received {get;set;}
        public int Orders,Closes;public bool ProtectedAfterEvent,Unprotected,FailOrder,IntentPersisted;public string? Journal;public bool HoldHistory;
        public TaskCompletionSource HistoryEntered=new(TaskCreationOptions.RunContinuationsAsynchronously),HistoryRelease=new(TaskCreationOptions.RunContinuationsAsynchronously);
        public Task Connect(AppCredentials app,TokenSet token,long accountId=48463366L,bool live=false)=>Task.CompletedTask;
        public Task<JsonElement> Request(int type,object payload,int expected)
        {
            if(type==2145&&HoldHistory){HistoryEntered.TrySetResult();return WaitHistory();}
            if(type==2124&&ProtectedAfterEvent)Received?.Invoke(2126,E(new{ctidTraderAccountId=123,executionType=3,position=new{positionId=999,positionStatus=1,tradeData=new{label="AurumMomentum",volume=100}}}));
            object result=type switch {
                2149=>new {permissionScope=1,ctidTraderAccount=new[]{new{ctidTraderAccountId=123,traderLogin=456,brokerTitleShort="FxPro",isLive=false}}},
                2121=>new {trader=new{balance=5000000,moneyDigits=2,depositAssetId=1}},
                2112=>new {asset=new[]{new{assetId=1,name="USD"}}},
                2114=>new {symbol=new[]{new{symbolId=41,symbolName="XAUUSD",quoteAssetId=1,enabled=true}}},
                2116=>new {symbol=new[]{new{symbolId=41,digits=2,minVolume=100,maxVolume=1000000,stepVolume=100,enableShortSelling=true}}},
                2145=>new {hasMore=false,tickData=Array.Empty<object>()},
                2124=>new {position=Unprotected?new object[]{new{positionId=999,tradeData=new{label="AurumMomentum",volume=100}}}:ProtectedAfterEvent?new object[]{new{positionId=999,tradeData=new{label="AurumMomentum",volume=100},stopLoss=3010,takeProfit=2900}}:Array.Empty<object>()},
                _=>new {}
            };
            if(type==2106)
            {
                Orders++;
                if(Journal is not null)IntentPersisted=JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(Journal),Json)!.PendingOrder==E(payload).GetProperty("clientOrderId").GetString();
                if(FailOrder)throw new IOException("Simulated connection loss after send.");
            }
            if(type==2111){Closes++;var p=E(payload);Check(Integer(p,"positionId")==999&&Integer(p,"volume")==100,"close exact affected position and volume");}
            return Task.FromResult(E(result));
        }
        async Task<JsonElement> WaitHistory(){await HistoryRelease.Task;return E(new{hasMore=false,tickData=Array.Empty<object>()});}
        public void Dispose(){}
    }
}
