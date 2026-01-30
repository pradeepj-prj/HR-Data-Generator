"""HR Data Generator - Generate realistic SuccessFactors-style HR datasets."""

from .attrition import (
    AttritionModel,
    FactorStrategy,
    FormulaStrategy,
    LookupStrategy,
    RangeLookupStrategy,
)
from .generator import HRDataGenerator, generate_hr_data
from .loader import (
    load_all_reference_data,
    load_employee_data,
    load_job_data,
    load_location_data,
    load_org_data,
)

__version__ = "0.1.0"
__all__ = [
    "generate_hr_data",
    "HRDataGenerator",
    "load_employee_data",
    "load_job_data",
    "load_org_data",
    "load_location_data",
    "load_all_reference_data",
    # Attrition model (for advanced customization)
    "AttritionModel",
    "FactorStrategy",
    "LookupStrategy",
    "RangeLookupStrategy",
    "FormulaStrategy",
]
