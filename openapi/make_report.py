#!/usr/bin/env python3
"""Render verified quote-replay results; no network access or account credentials."""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

folder = Path(sys.argv[1])
report = json.loads((folder / 'results.json').read_text())
results = report['results']
start = min(r['startUtc'] for r in results)
end = max(r['endUtcExclusive'] for r in results)
full = [r for r in results if r['startUtc'] == start and r['endUtcExclusive'] == end]
with (folder / 'results.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(results[0]))
    writer.writeheader(); writer.writerows(results)
for r in results:
    source = folder / (r['name'] + '-trades.json')
    trades = json.loads(source.read_text())
    if trades:
        with source.with_suffix('.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(trades[0]))
            writer.writeheader(); writer.writerows(trades)

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                     'text.parse_math': False, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.labelcolor': '#384559', 'text.color': '#182236',
                     'xtick.color': '#667085', 'ytick.color': '#667085'})
fig, (ax, monthly) = plt.subplots(2, 1, figsize=(12.5, 8.7), gridspec_kw={'height_ratios': [2.2, 1]})
fig.set_facecolor('#f7f9fc')
for a in (ax, monthly):
    a.set_facecolor('#fff'); a.grid(axis='y', color='#e6ebf2', linewidth=.8); a.set_axisbelow(True)
plotted = [r for r in full if r['swapEnabled']] or full
keys = sorted(set((r['initial'], r['rr']) for r in plotted))
palette = plt.get_cmap('tab10')
colors = {key: palette(i % 10) for i, key in enumerate(keys)}
for r in plotted:
    daily = json.loads((folder / (r['name'] + '-daily.json')).read_text())
    dates = [datetime.fromisoformat(start.replace('Z', '+00:00'))]
    equity = [0.0]
    for item in daily:
        dates.append(datetime.fromisoformat(item['date'] + 'T23:59:59+00:00'))
        equity.append(item['equity'] - r['initial'])
    stress = r['slippageUsdOz'] > 0
    label = f"${r['initial']:,.0f} · RR 1:{r['rr']:g} · slip ${r['slippageUsdOz']:g}/oz"
    if not r['swapEnabled']: label += ' · swap off'
    ax.plot(dates, equity, label=label, color=colors[(r['initial'], r['rr'])], linestyle='--' if stress else '-', linewidth=1.7, alpha=.8)
ax.axhline(0, color='#687384', linewidth=.8)
ax.set_ylabel('Net equity change · USD')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
ax.legend(loc='best', frameon=False, fontsize=8)
ax.set_title('Continuous simulation · separate starting accounts', loc='left', fontweight='bold', pad=15)
monthly_results = [r for r in results if r['swapEnabled'] and
                   (r['startUtc'] != start or r['endUtcExclusive'] != end)]
months = sorted(set(r['startUtc'][:7] for r in monthly_results))
if months:
    slip = min(r['slippageUsdOz'] for r in monthly_results)
    monthly_results = [r for r in monthly_results if r['slippageUsdOz'] == slip]
    variants = sorted(set((r['initial'], r['rr']) for r in monthly_results))
    width = .8 / len(variants)
    for i, (capital, rr) in enumerate(variants):
        values = [next((r['equityNet'] for r in monthly_results if r['initial'] == capital and r['rr'] == rr and r['startUtc'].startswith(m)), 0) for m in months]
        offset = (i - (len(variants) - 1) / 2) * width
        monthly.bar([j + offset for j in range(len(months))], values, width=width,
                    label=f'${capital:,.0f} · RR 1:{rr:g}', color=colors[(capital, rr)])
    monthly.set_xticks(range(len(months)), months)
    monthly.legend(frameon=False, fontsize=8)
    monthly.set_title(f'Independent monthly accounts · slip ${slip:g}/oz', loc='left', fontweight='bold', pad=12)
    monthly.set_ylabel('Net equity change · USD')
else:
    monthly.axis('off')
    rows = plotted[:6]
    def pf(value): return '—' if value is None else f'{value:.2f}'
    text = '\n'.join(f"${r['initial']:,.0f} · RR 1:{r['rr']:g} · {r['trades']} trades · PF {pf(r['profitFactor'])} · DD {r['maxEquityDDPct']:.2f}%" for r in rows)
    monthly.text(.03, .9, text, va='top', fontsize=10, transform=monthly.transAxes)
risks = ', '.join(f"{v:g}%" for v in sorted(set(r.get('riskPercent', .25) for r in full)))
halts = ', '.join(f"{v:g}%" for v in sorted(set(r.get('maxDrawdownPercent', 5) for r in full)))
fig.suptitle(f"XAUUSD · FxPro bid/ask tick replay\n{start[:10]} to {end[:10]} (end exclusive)", x=.07, ha='left', fontsize=18, fontweight='bold')
fig.text(.07, .03, f"Costs use broker metadata; historical commission/swap schedules are not verified.\n1s entry delay · risk {risks} · ~1x notional cap · one position · closed-balance halt {halts}.\nQuote replay is research, not a live performance claim.", fontsize=9, color='#667085')
fig.subplots_adjust(top=.83, bottom=.17, left=.08, right=.97, hspace=.5)
fig.savefig(folder / 'equity.png', dpi=160, facecolor=fig.get_facecolor())
plt.close(fig)

rows = ['# Backtest XAUUSD trên dữ liệu FxPro', '',
        f"Kỳ {start[:10]} đến trước {end[:10]}. Risk: {risks}; ngưỡng dừng mở mới: {halts}. Nguồn: bid/ask tick từ FxPro cTrader demo, {report['quotes']:,} snapshot báo giá. Đây là mô phỏng local, không phải báo cáo của cTrader Strategy Tester.", '',
        '| Vốn | RR | Trượt market/oz | Lệnh đóng | Win rate | P&L equity | DD equity | PF | Dừng mở mới |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|:---:|']
for r in full:
    pf = f"{r['profitFactor']:.2f}" if r['profitFactor'] is not None else '—'
    rows.append(f"| ${r['initial']:,.0f} | 1:{r['rr']:g} | ${r['slippageUsdOz']:.2f} | {r['trades']} | {r['winRate']:.1f}% | ${r['equityNet']:,.2f} | {r['maxEquityDDPct']:.2f}% | {pf} | {'Có' if r['halted'] else 'Không'} |")
rows += ['', '![Equity](equity.png)', '',
         'P&L equity gồm giá trị đánh dấu của vị thế còn mở và phí đóng ước tính; không ép đóng lệnh cuối kỳ. Chạy từng tháng là các tài khoản mô phỏng độc lập, đặt lại vốn và ngưỡng dừng đầu tháng; không cộng chúng thành kết quả tài khoản liên tục.', '',
         'Commission: đọc từ metadata được lưu cùng dữ liệu. Swap dùng snapshot metadata lúc lấy dữ liệu, cùng một mức cho cả kỳ; bản tắt swap là kiểm tra độ nhạy, không đại diện phí giao dịch thực tế. Chưa có lịch swap lịch sử. Lịch rollover dùng 21:59 giờ UK theo FxPro, chưa đối soát từng lần thu phí trên nền tảng.', '',
         'Tái sử dụng trực tiếp AsiaSession.cs của cBot. Không tối ưu tham số trong đợt này. Tháng 1–4 nằm ngoài giai đoạn so RR tháng 5–11 trước đó; nghiên cứu cũ từng xem giai đoạn này, vì vậy không coi là tập kiểm chứng hoàn toàn chưa nhìn thấy.', '',
         'Đối chiếu 1.320 nến M1: ba phút có cực trị khác tick endpoint tối đa 0,04 USD/oz; tải riêng các phút này xác nhận tick lưu trùng khớp. Chi tiết trong data-audit.json.\n\nDữ liệu từng lệnh, equity ngày và các lượt bật/tắt swap nằm cạnh báo cáo dưới dạng JSON/CSV. Kịch bản trượt giá cố định không đo độ sâu thị trường, độ trễ thật hay khả năng khớp của tài khoản live.', '',
         'Nguồn đối chiếu: [FxPro commission và swap](https://www.fxpro.com/commissions-swap-charges), [cTrader historical ticks](https://help.ctrader.com/open-api/symbol-data/).']
(folder / 'report.md').write_text('\n'.join(rows) + '\n')
print(folder / 'report.md')
print(folder / 'equity.png')
