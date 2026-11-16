using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Xauusd;

static class PaPathAudit
{
    internal sealed class Path
    {
        public required DateTime SignalUtc {get;init;}
        public required bool Buy {get;init;}
        public required double Range {get;init;}
        public required int HorizonMinutes {get;init;}
        public required RangeSupplyDemand.ZoneState Zone {get;init;}
        public required RangePaStructure.Decision Decision {get;init;}
        public string SignalSession=>AsiaSession.GetEntrySession(SignalUtc,true,true).ToString();
        public DateTime? EntryUtc {get;private set;}
        public DateTime? HorizonUtc {get;private set;}
        public double? Entry {get;private set;}
        public double? Stop {get;private set;}
        public double? Risk {get;private set;}
        public double? Hypothetical3RTarget {get;private set;}
        public double? SwingTarget {get;private set;}
        public double? Spread {get;private set;}
        public bool? SpreadAllowed {get;private set;}
        public bool? RangeSignalValidAtEntry {get;private set;}
        public double MfeR {get;private set;}
        public double MaeR {get;private set;}
        public string ThreeROutcome {get;private set;}="pending";
        public string SwingOutcome {get;private set;}="pending";
        public DateTime? ThreeRTouchUtc {get;private set;}
        public DateTime? SwingTouchUtc {get;private set;}
        public bool CompleteHorizon {get;private set;}
        public string? CensorReason {get;private set;}
        public bool Done {get;private set;}
        public DateTime? LastQuoteUtc {get;private set;}
        public double? LastMarkoutR {get;private set;}
        public void Observe(BacktestRunner.Quote q)
        {
            if(Done)return;
            if(EntryUtc is null)
            {
                if(q.Time<SignalUtc.AddSeconds(1))return;
                if(q.Time>SignalUtc.AddSeconds(6)){Finish("entry-unavailable");return;}
                EntryUtc=q.Time;HorizonUtc=q.Time.AddMinutes(HorizonMinutes);Spread=q.Ask-q.Bid;SpreadAllowed=Spread<=Range*.2+1e-9;RangeSignalValidAtEntry=Buy?q.Bid>Zone.Low&&q.Bid<=Zone.High+Range:q.Ask<Zone.High&&q.Bid>=Zone.Low-Range;
                Entry=(Buy?q.Ask:q.Bid)+(Buy?.1:-.1);
                double buffer=Math.Max(Spread.Value,Range*.1),distance=Math.Max(3,Buy?Entry.Value-(Zone.Low-buffer):Zone.High+buffer-Entry.Value);
                distance=Math.Ceiling(distance/.01-1e-9)*.01;Stop=Math.Round(Entry.Value+(Buy?-distance:distance),2,MidpointRounding.AwayFromZero);Risk=Math.Abs(Entry.Value-Stop.Value);
                Hypothetical3RTarget=Math.Round(Entry.Value+(Buy?3:-3)*Risk.Value,2,MidpointRounding.AwayFromZero);
                SwingTarget=Decision.Target is {} target?Math.Round(target,2,MidpointRounding.AwayFromZero):null;
                if(SwingTarget is null)SwingOutcome="no-target";else if(Buy?SwingTarget<=Entry:SwingTarget>=Entry)SwingOutcome="target-passed";
            }
            if(LastQuoteUtc is {} previous)
            {
                if(q.Time>HorizonUtc){Finish(HorizonUtc-previous<=TimeSpan.FromSeconds(60)?null:"quote-gap");return;}
                if(q.Time-previous>TimeSpan.FromSeconds(60)){Finish("quote-gap");return;}
            }
            double exit=Buy?q.Bid:q.Ask,r=(Buy?exit-Entry!.Value:Entry!.Value-exit)/Risk!.Value;
            MfeR=Math.Max(MfeR,r);MaeR=Math.Max(MaeR,-r);LastQuoteUtc=q.Time;LastMarkoutR=r;
            bool sl=Buy?exit<=Stop:exit>=Stop;
            if(ThreeROutcome=="pending"&&(sl||(Buy?exit>=Hypothetical3RTarget:exit<=Hypothetical3RTarget)))
            {ThreeROutcome=sl?"sl":"3r";ThreeRTouchUtc=q.Time;}
            if(SwingOutcome=="pending"&&(sl||(Buy?exit>=SwingTarget:exit<=SwingTarget)))
            {SwingOutcome=sl?"sl":"swing-tp";SwingTouchUtc=q.Time;}
            if(q.Time==HorizonUtc)Finish(null);
        }
        public void Finish(string? reason)
        {
            Done=true;CensorReason=reason;CompleteHorizon=reason is null;
            if(ThreeROutcome=="pending")ThreeROutcome=reason is null?"time":"censored";
            if(SwingOutcome=="pending")SwingOutcome=reason is null?"time":"censored";
        }
    }
    public static void Run(string[] args)
    {
        if(args.Length!=4)throw new ArgumentException("audit-pa-paths START END OUTPUT (end exclusive)");
        var start=DateTime.ParseExact(args[1],"yyyy-MM-dd",CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal);
        var end=DateTime.ParseExact(args[2],"yyyy-MM-dd",CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal);
        new ResearchConfig(Start:args[1],End:args[2]).Validate();Directory.CreateDirectory(args[3]);
        double[] sizes={2,3,5};var engines=sizes.Select(s=>new RangeSupplyDemand(s,3)).ToArray();var structures=sizes.Select(_=>new RangePaStructure()).ToArray();var closes=new double[3];var versions=new long[3];
        for(int i=0;i<3;i++){int n=i;engines[i].OnBar=(b,index)=>{structures[n].Observe(b,index);closes[n]=b.Close;};}
        var active=new List<Path>();var results=new List<Path>();var files=new List<object>();long quotes=0,rejected=0;
        for(var day=start.AddDays(-4);day<=end;day=day.AddDays(1))
        {
            string path=System.IO.Path.Combine("data","fxpro-v2",$"XAUUSD-{day:yyyy-MM-dd}.csv.gz");if(!File.Exists(path)){if(day>=start&&day<end)throw new IOException("Missing audit data.");continue;}
            foreach(var q in BacktestRunner.ReadQuotes(path))
            {
                if(q.Time>end.AddMinutes(30).AddSeconds(6))break;
                if(!double.IsFinite(q.Bid+q.Ask)||q.Bid<=0||q.Ask<q.Bid){rejected++;continue;}
                if(q.Time>=start){quotes++;foreach(var observation in active)observation.Observe(q);active.RemoveAll(p=>p.Done);}
                if(q.Time>=end)continue;
                for(int i=0;i<3;i++)
                {
                    var engine=engines[i];engine.Observe(q);
                    if(engine.SignalVersion==versions[i])continue;versions[i]=engine.SignalVersion;
                    if(q.Time<start||engine.SignalZone is not {} zone)continue;
                    var decision=structures[i].Freeze(zone.Long,closes[i],engine.ConfirmedUtc);
                    foreach(var horizon in new[]{5,30})
                    {
                        var observation=new Path{SignalUtc=q.Time,Buy=zone.Long,Range=sizes[i],HorizonMinutes=horizon,Zone=zone,Decision=decision};
                        active.Add(observation);results.Add(observation);
                    }
                }
            }
            using var stream=File.OpenRead(path);files.Add(new{date=day.ToString("yyyy-MM-dd"),sha256=Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant()});
            Console.WriteLine($"{day:yyyy-MM-dd}: {results.Count/2} PA observations, {active.Count} active horizon paths");
        }
        foreach(var p in active)p.Finish("end-of-data");
        File.WriteAllText(System.IO.Path.Combine(args[3],"paths.json"),JsonSerializer.Serialize(results,ExecutionFiles.Json));
        File.WriteAllText(System.IO.Path.Combine(args[3],"manifest.json"),JsonSerializer.Serialize(new{schemaVersion=1,start,endUtcExclusive=end,generatedUtc=DateTime.UtcNow,kind="observational-not-trading-pnl",slippageUsdOz=.1,horizonsMinutes=new[]{5,30},minimumStop=3,quotes,rejected,files,signals=results.Count/2},ExecutionFiles.Json));
    }
    public static void Checks()
    {
        var day=new DateTime(2026,1,5,0,0,0,DateTimeKind.Utc);
        Path Make(bool buy=true)=>new(){SignalUtc=day,Buy=buy,Range=3,HorizonMinutes=5,Zone=new(buy,97.3,102.7,day,1,buy?109:91),Decision=new("Unknown",buy?109:91,day,day)};
        BacktestRunner.Quote Q(double seconds,double bid,double ask)=>new(new DateTimeOffset(day.AddSeconds(seconds)).ToUnixTimeMilliseconds(),bid,ask);
        var p=Make();p.Observe(Q(.5,100,100.1));if(p.Entry is not null)throw new Exception("Premature audit entry");p.Observe(Q(1,100,100.1));if(p.MaeR<=0)throw new Exception("Spread not reflected in MAE");
        p.Observe(Q(2,96,96.1));p.Observe(Q(3,120,120.1));if(p.ThreeROutcome!="sl")throw new Exception("Future rally overwrote first stop");
        var buy=Make();buy.Observe(Q(1,100,100.1));buy.Observe(Q(2,112,112.1));if(buy.ThreeROutcome!="3r")throw new Exception("Long target not recognized");
        var sell=Make(false);sell.Observe(Q(1,100,100.1));sell.Observe(Q(2,88,88.1));if(sell.ThreeROutcome!="3r")throw new Exception("Short target not recognized");
        var gap=Make();gap.Observe(Q(1,100,100.1));gap.Observe(Q(90,120,120.1));if(gap.ThreeROutcome!="censored"||gap.CensorReason!="quote-gap")throw new Exception("Gap gave false target");
        var timeout=Make();for(int i=1;i<=301;i+=30)timeout.Observe(Q(i,100,100.1));timeout.Observe(Q(302,120,120.1));if(timeout.ThreeROutcome!="time"||!timeout.CompleteHorizon||timeout.MfeR>1)throw new Exception("Future price used after time horizon");
        var boundary=Make();for(int i=1;i<=271;i+=30)boundary.Observe(Q(i,100,100.1));boundary.Observe(Q(1000,120,120.1));if(boundary.ThreeROutcome!="time"||!boundary.CompleteHorizon)throw new Exception("Gap beyond horizon changed completed timeout");
        var incomplete=Make();incomplete.Observe(Q(1,100,100.1));incomplete.Finish("end-of-data");if(incomplete.ThreeROutcome!="censored"||incomplete.CompleteHorizon)throw new Exception("Truncated data treated as complete");
        var missing=Make();missing.Observe(Q(7,100,100.1));if(missing.CensorReason!="entry-unavailable")throw new Exception("Stale entry accepted");
        Console.WriteLine("PA path audit PASS: delayed executable entry, spread MAE, mirrored targets, first-touch order, gap/entry censoring and horizon causality.");
    }
}
