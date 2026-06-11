"""Run Module 1 on a case and emit chart, Excel, PDF and PPTX reports."""
import os
from nexa_toolkit.engine import DesignPoint, solve
from nexa_toolkit.reporting.charts import make_chart
from nexa_toolkit.reporting.excel_report import build_excel
from nexa_toolkit.reporting.pdf_report import build_pdf
from nexa_toolkit.reporting.pptx_report import build_pptx

OUT = "/home/claude/reports"
os.makedirs(OUT, exist_ok=True)

# PLACEHOLDER data-centre case (swap in the real design point)
dp = DesignPoint(t_chw_out_c=10.0, t_cw_in_c=30.0, t_hot_c=90.0, q_evap_kw=500.0)
r = solve(dp)

make_chart(r, f"{OUT}/chart.png")
build_excel(dp, r, f"{OUT}/LiBr_chiller_sizing.xlsx")
build_pdf(dp, r, f"{OUT}/LiBr_chiller_sizing.pdf", f"{OUT}/_chart_pdf.png")
build_pptx(dp, r, f"{OUT}/LiBr_chiller_sizing.pptx", f"{OUT}/_chart_pptx.png")
print("reports written to", OUT)
for f in sorted(os.listdir(OUT)):
    print(" -", f)
