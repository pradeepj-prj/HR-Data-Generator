from pathlib import Path

CURR_DIR = Path(__file__).resolve().parent

CONFIG_DIR = CURR_DIR / "params"

EMPLOYEE_DATA_PATH = CONFIG_DIR / "employee_data.yaml"
