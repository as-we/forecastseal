"""The calculator page must give the same numbers as `fseal plan`. Runs the page's own maths in Node when it is installed."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from forecastseal import stats

PAGE = Path(__file__).resolve().parent.parent / "docs" / "plan-calculator.html"
node = shutil.which("node")


def js_values(cases):
    src = PAGE.read_text(encoding="utf-8")
    block = re.search(r"<script>\n// ---- pure maths.*?</script>", src, re.S).group(0)
    code = block.replace("<script>", "").replace("</script>", "")
    code += "\nconst cases=" + json.dumps(cases) + ";\nconsole.log(JSON.stringify(cases.map(c=>({"
    code += "n:FS.requiredN(c.d,c.sd,c.a),p:FS.powerScores(c.n,c.d,c.sd,c.a),m:FS.minDetectable(c.n,c.sd,c.a),"
    code += "rn:FS.requiredNRates(c.p1,c.p2,c.a),rp:FS.powerRates(c.n,c.p1,c.p2,c.a)}))));"
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_page_maths_matches_python():
    cases = [dict(d=0.01, sd=0.085, a=0.05, n=90, p1=0.7, p2=0.8), dict(d=0.05, sd=0.2, a=0.025, n=300, p1=0.5, p2=0.6),
             dict(d=0.2, sd=0.5, a=0.01, n=40, p1=0.3, p2=0.35)]
    got = js_values(cases)
    for c, g in zip(cases, got):
        assert g["n"] == stats.required_n(c["d"], c["sd"], c["a"])
        assert g["p"] == pytest.approx(stats.power(c["n"], c["d"], c["sd"], c["a"]), abs=2e-5)
        assert g["m"] == pytest.approx(stats.min_detectable(c["n"], c["sd"], c["a"]), rel=1e-6)
        assert abs(g["rn"] - stats.required_n_rates(c["p1"], c["p2"], c["a"])) <= 1
        assert g["rp"] == pytest.approx(stats.power_rates(c["n"], c["p1"], c["p2"], c["a"]), abs=2e-5)


def test_page_has_no_network_and_a_strict_policy():
    src = PAGE.read_text(encoding="utf-8")
    assert "default-src 'none'" in src
    external = re.findall(r"(?:src|href)=\"(https?://[^\"]+)\"", src)
    assert external == ["https://github.com/as-we/forecastseal"]       # one plain link to the project, nothing that loads a resource
    assert "fetch(" not in src and "XMLHttpRequest" not in src
