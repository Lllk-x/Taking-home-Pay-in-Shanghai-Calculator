"""
Shanghai take-home pay calculator (2024-07-01 → 2025-06-30 defaults)

- Social insurance (SI) employee rates (Shanghai):
  Pension 8%, Medical 2%, Unemployment 0.5%
  Bases clamped to: 7,384 ≤ base ≤ 36,921 (CNY)
- Housing Fund (HF) employee rate: configurable (typical 5-7%; default 7%)
  Base clamped to: 2,690 ≤ base ≤ 36,921 (CNY)
- IIT (wages) uses the cumulative withholding method with the national
  comprehensive-income brackets and quick deductions.
- Standard deduction: 5,000 CNY/month. You can add monthly special deductions.

Pass month_index=1.12, by default it assumes the same pay/deductions in prior
months; or pass `cumulative_prev_pay` (list) and `prev_withheld_tax` for exact runs.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict

@dataclass
class ShanghaiConfig:
    # Valid for 2024-07-01 to 2025-06-30 (update when Shanghai publishes new bases)
    si_floor: float = 7384.0
    si_cap: float = 36921.0
    hf_floor: float = 2690.0
    hf_cap: float = 36921.0
    # Employee contribution rates
    pension_rate_emp: float = 0.08
    medical_rate_emp: float = 0.02
    unemployment_rate_emp: float = 0.005
    # Housing Fund employee rate (choose within 0.05–0.07 typically)
    default_hf_rate_emp: float = 0.07
    # IIT standard deduction
    standard_deduction_monthly: float = 5000.0
    # Annual comprehensive-income brackets (up_to, rate, quick_deduction)
    brackets: List[Dict] = None

def default_config() -> ShanghaiConfig:
    return ShanghaiConfig(
        brackets=[
            {"up_to":  36000, "rate": 0.03, "quick":      0},
            {"up_to": 144000, "rate": 0.10, "quick":   2520},
            {"up_to": 300000, "rate": 0.20, "quick":  16920},
            {"up_to": 420000, "rate": 0.25, "quick":  31920},
            {"up_to": 660000, "rate": 0.30, "quick":  52920},
            {"up_to": 960000, "rate": 0.35, "quick":  85920},
            {"up_to": float("inf"), "rate": 0.45, "quick": 181920},
        ]
    )

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def calc_employee_social(gross: float, cfg: ShanghaiConfig, si_base: Optional[float]=None) -> dict:
    base = _clamp(si_base if si_base is not None else gross, cfg.si_floor, cfg.si_cap)
    pension = base * cfg.pension_rate_emp
    medical = base * cfg.medical_rate_emp
    unemployment = base * cfg.unemployment_rate_emp
    return {
        "base": base,
        "pension": pension,
        "medical": medical,
        "unemployment": unemployment,
        "total": pension + medical + unemployment,
    }

def calc_housing_fund(gross: float, cfg: ShanghaiConfig,
                      hf_rate: Optional[float]=None, hf_base: Optional[float]=None) -> dict:
    rate = cfg.default_hf_rate_emp if hf_rate is None else hf_rate
    base = _clamp(hf_base if hf_base is not None else gross, cfg.hf_floor, cfg.hf_cap)
    return {"rate": rate, "base": base, "amount": base * rate}

def _tax_on_cumulative_taxable(cum_taxable: float, cfg: ShanghaiConfig) -> float:
    t = max(0.0, cum_taxable)
    for b in cfg.brackets:
        if t <= b["up_to"]:
            return t * b["rate"] - b["quick"]
    # unreachable due to inf
    return t * 0.45 - 181920

def takehome_shanghai(
    gross_salary: float,
    month_index: int,
    cfg: ShanghaiConfig = None,
    *,
    special_deductions_monthly: float = 0.0,  # 子女教育、赡养老人、住房等“专项附加扣除”的月合计
    si_base: Optional[float] = None,          # 如单位申报的社保基数不同，可指定
    hf_rate: Optional[float] = None,          # 个人公积金比例（默认 7%）
    hf_base: Optional[float] = None,          # 如单位确定的公积金基数不同，可指定
    cumulative_prev_pay: Optional[List[float]] = None,  # 之前各月的实际税前工资列表
    prev_withheld_tax: float = 0.0,           # 累计已预扣个税（上月申报后数值）
) -> dict:
    """
    Returns a breakdown for the given month, including take-home pay and all components.
    """
    cfg = cfg or default_config()

    # Current month social + HF
    si = calc_employee_social(gross_salary, cfg, si_base=si_base)
    hf = calc_housing_fund(gross_salary, cfg, hf_rate=hf_rate, hf_base=hf_base)

    # Build cumulative figures used by the official cumulative withholding method
    if cumulative_prev_pay is None:
        prev_m = max(0, month_index - 1)
        cum_income = gross_salary * month_index
        # assume same settings in earlier months
        prev_si_total = calc_employee_social(gross_salary, cfg, si_base=si_base)["total"] * prev_m
        prev_hf_total = calc_housing_fund(gross_salary, cfg, hf_rate=hf_rate, hf_base=hf_base)["amount"] * prev_m
    else:
        if len(cumulative_prev_pay) != month_index - 1:
            raise ValueError("cumulative_prev_pay length must equal month_index - 1")
        cum_income = sum(cumulative_prev_pay) + gross_salary
        prev_si_total = sum(calc_employee_social(s, cfg, si_base=si_base)["total"] for s in cumulative_prev_pay)
        prev_hf_total = sum(calc_housing_fund(s, cfg, hf_rate=hf_rate, hf_base=hf_base)["amount"] for s in cumulative_prev_pay)

    cum_si = prev_si_total + si["total"]
    cum_hf = prev_hf_total + hf["amount"]
    cum_standard = cfg.standard_deduction_monthly * month_index
    cum_special = special_deductions_monthly * month_index

    cum_taxable = cum_income - cum_si - cum_hf - cum_standard - cum_special
    cum_tax_payable = _tax_on_cumulative_taxable(cum_taxable, cfg)
    tax_this_month = max(0.0, cum_tax_payable - prev_withheld_tax)

    takehome = gross_salary - si["total"] - hf["amount"] - tax_this_month

    return {
        "month_index": month_index,
        "gross_salary": float(gross_salary),
        "take_home": float(takehome),
        "tax_this_month": float(tax_this_month),
        "cumulative_tax_payable": float(cum_tax_payable),
        "pre_tax_deductions_this_month": float(si["total"] + hf["amount"]),
        "social_insurance": si,
        "housing_fund": hf,
        "cumulative_taxable_income": float(max(0.0, cum_taxable)),
        "assumptions": {
            "standard_deduction_monthly": cfg.standard_deduction_monthly,
            "special_deductions_monthly": special_deductions_monthly,
            "si_base_used_this_month": si["base"],
            "hf_base_used_this_month": hf["base"],
        },
    }

if __name__ == "__main__":
    cfg = default_config()
    # Example: 30,000 CNY/month, month 1, HF 7%, special deductions 1500
    for i in range(1,13):
        result = takehome_shanghai(125000, month_index=i, cfg=cfg, hf_rate=0.07, special_deductions_monthly=1500)
        from pprint import pprint
        pprint(result)
