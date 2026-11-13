"""Check the pure sizing/accounting path without loading tick/dataframe packages."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as Obj
source = Path(__file__).with_name('study.py')
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'equity_curve')
namespace = {'floor': math.floor, 'COMMISSION': .07, 'SCENARIOS': {'base': (1, .1)}}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
def result(fill, signal):
    row = Obj(risk_distance=2, entry=fill, signal_price=signal, net_usd_oz=1)
    trades = Obj(scenario=Obj(iloc=['base']), itertuples=lambda: iter([row]))
    return namespace['equity_curve'](trades, 50000, None)
assert result(3000, 3000)['max_oz'] == result(3200, 3000)['max_oz'] == 16
assert result(3000, 3200)['max_oz'] == 15
print('Research sizing checks PASS: quantity uses signal price with 1% headroom, independent of future fill.')
