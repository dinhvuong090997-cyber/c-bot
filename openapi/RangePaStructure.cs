using System.Text.Json;

// Streaming counterpart of dashboard/assets/price-action.js, verified against chart snapshots.
sealed class RangePaStructure
{
    internal sealed record Pivot(bool High,double Price,long Index,long KnownIndex,DateTime KnownUtc,DateTime PivotUtc);
    internal sealed record Decision(string Regime,double? Target,DateTime ConfirmedUtc,DateTime? TargetKnownUtc);
    readonly List<RangeBarBook.Bar> bars=new();
    public readonly List<Pivot> Pivots=new();
    Pivot? high,low;bool highBroken,lowBroken;DateTime previous;
    public string Regime {get;private set;}="Unknown";
    public void Observe(RangeBarBook.Bar bar,long index)
    {
        if(previous!=default&&(bar.Start.Date!=previous.Date||bar.Start-previous>TimeSpan.FromSeconds(60)))
        {bars.Clear();Pivots.Clear();high=low=null;highBroken=lowBroken=false;Regime="Unknown";}
        previous=bar.End;bars.Add(bar);if(bars.Count>5)bars.RemoveAt(0);
        if(bars.Count==5)
        {
            var p=bars[2];var neighbors=new[]{bars[0],bars[1],bars[3],bars[4]};
            if(neighbors.All(n=>p.High>n.High)){high=new(true,p.High,index-2,index,bar.End,p.End);Pivots.Add(high);highBroken=false;}
            if(neighbors.All(n=>p.Low<n.Low)){low=new(false,p.Low,index-2,index,bar.End,p.End);Pivots.Add(low);lowBroken=false;}
        }
        if(high is not null&&bar.Close>high.Price)highBroken=true;
        if(low is not null&&bar.Close<low.Price)lowBroken=true;
        var highs=Pivots.Where(p=>p.High).TakeLast(2).ToArray();var lows=Pivots.Where(p=>!p.High).TakeLast(2).ToArray();
        Regime="Unknown";
        if(highs.Length==2&&lows.Length==2)
        {
            int h=Math.Sign(highs[1].Price-highs[0].Price),l=Math.Sign(lows[1].Price-lows[0].Price);
            Regime=h==1&&l==1?"Uptrend":h==-1&&l==-1?"Downtrend":h==0||l==0?"Transition":"Range / mixed";
        }
        if(Regime=="Uptrend"&&lowBroken||Regime=="Downtrend"&&highBroken)Regime="Transition";
    }
    public Decision Freeze(bool buy,double bidClose,DateTime time)
    {
        var target=Pivots.Where(p=>p.High==buy&&(buy?p.Price>bidClose:p.Price<bidClose)).OrderBy(p=>Math.Abs(p.Price-bidClose)).FirstOrDefault();
        if(target is not null&&target.KnownUtc>time)throw new InvalidOperationException("Future PA target rejected.");
        return new(Regime,target?.Price,time,target?.KnownUtc);
    }
}

static class PaToolkitChecks
{
    static void Check(bool condition,string message){if(!condition)throw new Exception("PA toolkit: "+message);}
    public static void Run()
    {
        var model=new RangePaStructure();double[] values={101,102,105,103,102,101,102,106,103,102,101.5,102,107,104,103};var day=new DateTime(2026,1,5,0,0,0,DateTimeKind.Utc);
        for(int i=0;i<values.Length;i++)
        {
            double c=values[i];model.Observe(new(day.AddSeconds(i),day.AddSeconds(i).AddMilliseconds(500),c,c+.4,c-.4,c),i+1);
            if(i==3)Check(model.Pivots.Count==0,"pivot unknown before two right bars");
            if(i==4)Check(model.Pivots[0].Index==3&&model.Pivots[0].KnownIndex==5,"pivot anchored then confirmed causally");
        }
        Check(model.Regime=="Uptrend","higher highs and lows");var frozen=model.Freeze(true,104,day.AddSeconds(15));Check(frozen.Target==105.4,"nearest known swing target");
        model.Observe(new(day.AddSeconds(15),day.AddSeconds(15.5),103,103,100.4,100.5),16);Check(model.Regime=="Transition","supporting swing break invalidates trend");Check(frozen.Regime=="Uptrend"&&frozen.Target==105.4,"frozen decision not changed by future bar");
        model.Observe(new(day.AddMinutes(3),day.AddMinutes(3.1),103,106,102,105),17);Check(model.Pivots.Count==0&&model.Regime=="Unknown","gap context reset");Check(model.Freeze(true,105,day.AddMinutes(4)).Target is null,"no invented target");
        Console.WriteLine("PA toolkit C# PASS: causal pivots, nearest frozen targets, transition and gap reset.");
    }
    public static void ExportParity(string directory,string output)
    {
        var checks=new List<object>();
        foreach(var path in Directory.EnumerateFiles(directory,"range-pa-2026-*-r*.json").Order())
        {
            using var doc=JsonDocument.Parse(File.ReadAllText(path));var root=doc.RootElement;var model=new RangePaStructure();var events=root.GetProperty("events").EnumerateArray().Where(e=>e.GetProperty("kind").GetString()=="confirmed").ToArray();
            int index=0;
            foreach(var b in root.GetProperty("bars").EnumerateArray())
            {
                index++;model.Observe(new(b.GetProperty("startUtc").GetDateTime(),b.GetProperty("endUtc").GetDateTime(),b.GetProperty("open").GetDouble(),b.GetProperty("high").GetDouble(),b.GetProperty("low").GetDouble(),b.GetProperty("close").GetDouble()),index);
                var targets=events.Where(e=>e.GetProperty("barIndex").GetInt64()==index).Select(e=>new{buy=e.GetProperty("zone").GetProperty("long").GetBoolean(),decision=model.Freeze(e.GetProperty("zone").GetProperty("long").GetBoolean(),b.GetProperty("close").GetDouble(),b.GetProperty("endUtc").GetDateTime())}).ToArray();
                checks.Add(new{file=Path.GetFileName(path),cursor=index-1,regime=model.Regime,pivots=model.Pivots.Select(p=>new{high=p.High,price=p.Price,index=p.Index,knownIndex=p.KnownIndex}).ToArray(),targets});
            }
        }
        File.WriteAllText(output,JsonSerializer.Serialize(checks,ExecutionFiles.Json));Console.WriteLine($"Exported {checks.Count} PA prefix parity frames.");
    }
}
