import numpy as np
from datetime import date, timedelta
import random

def get_age_gender(employee_data: dict): 
    age = np.random.randint(low=employee_data["age_min"], high=employee_data["age_max"])

    gender_roll = np.random.rand()
    if gender_roll < employee_data["prob_neutral"]: 
        gender = "na"
    elif gender_roll < employee_data["prob_female"]:
        gender = "female"
    else: 
        gender = "male"

    return age, gender


def get_name(gender: str, employee_data: dict): 
    if gender == "female": 
        first_name_choices = employee_data["female_names"]
    elif gender == "male": 
        first_name_choices = employee_data["male_first_names"]
    else: 
        first_name_choices = employee_data["neutral_names"]
    
    first_name = random.choice(first_name_choices)
    last_name = random.choice(employee_data["male_last_names"])

    return first_name, last_name

def get_hiring_date(age): 
    today = date.today()
    start_year = today.year - age + 21
    if start_year > today.year: 
        return today 
    else: 
        start = date(start_year, 1, 1)
        end = today 
        delta = end - start
        hiring_date = start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))

        return hiring_date
    
def generate_employees(n, employee_data): 
    employees = {}
    for i in range(n): 
        age, gender = get_age_gender(employee_data)
        first_name, last_name = get_name(gender, employee_data)
        hiring_date = get_hiring_date(age)
        employees[i+1] = {
            'age': age, 
            'gender': gender, 
            'first_name': first_name, 
            'last_name': last_name, 
            'hiring_date': hiring_date
        }
    
    return employees