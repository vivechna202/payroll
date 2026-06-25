#!/usr/bin/env python
"""
Test script for dynamic TDS projection model.
Tests the new calculate_tds_with_projection() function with sample data.
"""

import sys
sys.path.insert(0, '/c/Users/admin/payroll/taxation_prototype')

from services.tax_service import (
    calculate_tds_with_projection,
    calculate_projected_annual_income,
    get_fy_month_number,
    get_remaining_months_in_fy,
    get_actual_income_till_date,
    get_latest_monthly_salary
)
from config import CURRENT_FY
import json

def test_fy_helpers():
    """Test financial year helper functions."""
    print("\n=== Testing FY Helper Functions ===")
    
    # Test month conversion
    test_cases = [
        (4, 1),   # April = FY month 1
        (5, 2),   # May = FY month 2
        (6, 3),   # June = FY month 3
        (12, 9),  # December = FY month 9
        (3, 12),  # March = FY month 12
        (1, 10),  # January = FY month 10
    ]
    
    for cal_month, expected_fy_month in test_cases:
        result = get_fy_month_number(cal_month)
        status = "✓" if result == expected_fy_month else "✗"
        print(f"  {status} Calendar month {cal_month} -> FY month {result} (expected {expected_fy_month})")
    
    # Test remaining months calculation
    print("\n  Remaining months in FY:")
    for cal_month in [4, 5, 6, 12, 3]:
        remaining = get_remaining_months_in_fy(cal_month)
        print(f"    Month {cal_month}: {remaining} months remaining")


def test_projection():
    """Test income projection for a sample employee."""
    print("\n=== Testing Income Projection ===")
    
    employee_id = "EMP001"
    fy = CURRENT_FY
    current_month = 6  # June
    
    projection = calculate_projected_annual_income(employee_id, fy, current_month)
    
    print(f"\n  Employee: {employee_id}, FY: {fy}, Current Month: June (6)")
    print(f"  Actual income till date: ₹{projection['actual_income_till_date']:,.2f}")
    print(f"  Latest monthly salary: ₹{projection['latest_monthly_salary']:,.2f}")
    print(f"  Remaining months: {projection['remaining_months']}")
    print(f"  Projected future income: ₹{projection['projected_future_income']:,.2f}")
    print(f"  Bonus income: ₹{projection['bonus_income']:,.2f}")
    print(f"  PROJECTED ANNUAL INCOME: ₹{projection['projected_annual_income']:,.2f}")


def test_tds_calculation():
    """Test TDS calculation with projection model."""
    print("\n=== Testing TDS Calculation with Projection ===")
    
    employee_id = "EMP001"
    month = 6  # June
    fy = CURRENT_FY
    regime = "NEW"
    
    employee_deductions = {
        "basic_salary": 50000,
        "section_80C": 50000,
        "section_80D": 25000,
        "hra_exemption": 15000
    }
    
    tds_result = calculate_tds_with_projection(
        employee_id, month, fy, regime, employee_deductions
    )
    
    print(f"\n  Employee: {employee_id}, Month: June, FY: {fy}, Regime: {regime}")
    print(f"  Projected Annual Income: ₹{tds_result['projected_annual_income']:,.2f}")
    print(f"  Annual Taxable Income: ₹{tds_result['annual_taxable_income']:,.2f}")
    print(f"  Estimated Annual Tax: ₹{tds_result['estimated_annual_tax']:,.2f}")
    print(f"  TDS Deducted Till Date: ₹{tds_result['tds_deducted_till_date']:,.2f}")
    print(f"  Remaining Tax: ₹{tds_result['remaining_tax']:,.2f}")
    print(f"  Remaining Months: {tds_result['remaining_months']}")
    print(f"  >>> MONTHLY TDS (Projection): ₹{tds_result['monthly_tds']:,.2f}")
    
    print(f"\n  Projection Details:")
    for key, val in tds_result['projection_details'].items():
        if isinstance(val, (int, float)):
            print(f"    {key}: {val}")


def test_comparison_old_vs_new():
    """Compare old annualization vs new projection model."""
    print("\n=== Comparing Old vs New TDS Model ===")
    
    from services.tax_service import calculate_tds, calculate_taxable_income, apply_new_regime_slabs, apply_cess
    from config import PF_PERCENTAGE
    
    employee_id = "EMP001"
    month = 6
    fy = CURRENT_FY
    regime = "NEW"
    
    employee_deductions = {
        "basic_salary": 50000,
        "section_80C": 50000,
        "section_80D": 25000,
        "hra_exemption": 15000
    }
    
    # Old method
    monthly_gross = 75000
    old_monthly_tds = calculate_tds(monthly_gross, regime, employee_deductions)
    old_annual_tds = old_monthly_tds * 12
    
    # New method
    new_result = calculate_tds_with_projection(
        employee_id, month, fy, regime, employee_deductions
    )
    new_monthly_tds = new_result['monthly_tds']
    new_annual_tds = new_result['estimated_annual_tax']
    
    print(f"\n  Employee: {employee_id}, Month: June, Regime: {regime}")
    print(f"\n  OLD MODEL (Simple annualization: monthly × 12):")
    print(f"    Monthly Salary: ₹{monthly_gross:,.2f}")
    print(f"    Monthly TDS: ₹{old_monthly_tds:,.2f}")
    print(f"    Annualized TDS: ₹{old_annual_tds:,.2f}")
    
    print(f"\n  NEW MODEL (Dynamic projection from payroll history):")
    print(f"    Projected Annual Income: ₹{new_result['projected_annual_income']:,.2f}")
    print(f"    Monthly TDS (projected): ₹{new_monthly_tds:,.2f}")
    print(f"    Annualized TDS: ₹{new_annual_tds:,.2f}")
    
    diff = abs(new_annual_tds - old_annual_tds)
    if new_annual_tds > old_annual_tds:
        print(f"\n  📊 NEW MODEL results in HIGHER TDS: +₹{diff:,.2f} annually")
    elif new_annual_tds < old_annual_tds:
        print(f"\n  📊 NEW MODEL results in LOWER TDS: -₹{diff:,.2f} annually")
    else:
        print(f"\n  📊 Both models give same TDS")


if __name__ == "__main__":
    print("╔════════════════════════════════════════════════════════════╗")
    print("║  TDS Projection Model - Test Suite                         ║")
    print("╚════════════════════════════════════════════════════════════╝")
    
    try:
        test_fy_helpers()
        test_projection()
        test_tds_calculation()
        test_comparison_old_vs_new()
        
        print("\n" + "="*60)
        print("✓ All tests completed successfully!")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ Test failed with error:")
        print(f"  {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
